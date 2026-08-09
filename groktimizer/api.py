"""Authenticated HTTP gateway for the durable groktimizer control plane."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from groktimizer.cli.main import _client
from groktimizer.config import Config, load_config
from groktimizer.core.registry import Registry
from groktimizer.core.store import SCHEMA_VERSION, Store

PROJECT_NAME = re.compile(r"^[a-z0-9]{1,24}$")
SANDBOX_NAME = re.compile(r"^gtz-[a-z0-9]{1,24}-[a-z0-9]{1,24}-[a-z0-9]{1,24}$")
EMPTY_BASELINE = {
    "hardware": {"gpu": "unavailable", "vramGb": 0, "contextTokens": 0},
    "latency": [],
    "throughput": [],
    "accuracy": [],
}
APP_VERSION = version("groktimizer")


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class CommandError(RuntimeError):
    def __init__(self, args: tuple[str, ...], message: str, *, timed_out: bool = False):
        super().__init__(message)
        self.args_run = args
        self.timed_out = timed_out


class ProjectRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8_000)
    project: str


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    client_id: str = Field(alias="clientId", min_length=1, max_length=160)
    mode: str = "queue"
    retry: bool = False

    model_config = ConfigDict(populate_by_name=True)


class StreamTicketRequest(BaseModel):
    after: int = Field(default=0, ge=0)
    runtime_id: str | None = Field(default=None, alias="runtimeId", max_length=160)

    model_config = ConfigDict(populate_by_name=True)


def _config_path() -> Path:
    return Path(os.environ.get("GTZ_CONFIG", "groktimizer.toml")).expanduser().resolve()


def _config() -> Config:
    path = _config_path()
    if not path.is_file():
        raise ApiError(503, "Control plane is not configured")
    return load_config(path)


def _command_cwd() -> Path:
    return _config_path().parent


def _require_secret(name: str, minimum: int = 32) -> str:
    value = os.environ.get(name, "")
    if len(value) < minimum:
        raise ApiError(503, f"{name} is not configured")
    return value


def _public_url() -> str:
    raw = os.environ.get("GTZ_PUBLIC_URL", "").rstrip("/")
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError as error:
        raise ApiError(503, "GTZ_PUBLIC_URL is invalid") from error
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if not parsed.hostname or (parsed.scheme != "https" and not local):
        raise ApiError(503, "GTZ_PUBLIC_URL must use HTTPS")
    return raw


def _validate_project(project: str) -> str:
    if not PROJECT_NAME.fullmatch(project):
        raise ApiError(400, "Project id must contain 1–24 lowercase letters or numbers")
    return project


def _validate_sandbox(sandbox: str) -> str:
    if not SANDBOX_NAME.fullmatch(sandbox):
        raise ApiError(400, "Invalid sandbox")
    return sandbox


def _last_json(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("command returned no JSON object")


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


async def run_gtz(*args: str, timeout: float = 120) -> str:
    """Run the installed CLI with the API service's exact environment and store."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "groktimizer.cli.main",
        *args,
        cwd=_command_cwd(),
        env=os.environ.copy(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as error:
        await _terminate_process(process)
        raise CommandError(
            tuple(args), "control-plane command timed out", timed_out=True
        ) from error
    except asyncio.CancelledError:
        await _terminate_process(process)
        raise
    output = stdout.decode("utf-8", errors="replace")
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise CommandError(tuple(args), detail or "control-plane command failed")
    return output


def _configured_repo(cfg: Config) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(
        cfg.shared_repo.replace("git@github.com:", "https://github.com/")
    )
    parts = parsed.path.removesuffix(".git").strip("/").split("/")
    if parsed.hostname != "github.com" or len(parts) != 2:
        raise ValueError("shared_repo must be a GitHub repository")
    return parts[0], parts[1]


def _read_result_file(cfg: Config, filename: str) -> str:
    local = _command_cwd() / "results" / filename
    if local.is_file():
        return local.read_text()
    owner, repo = _configured_repo(cfg)
    url = (
        f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
        f"/contents/results/{urllib.parse.quote(filename)}?ref=main"
    )
    headers = {
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "groktimizer-control-plane",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        return response.read().decode("utf-8")


_baseline_value: dict[str, Any] | None = None
_baseline_expires = 0.0


def load_baseline() -> dict[str, Any]:
    global _baseline_expires, _baseline_value  # noqa: PLW0603
    now = time.monotonic()
    if _baseline_value is not None and now < _baseline_expires:
        return _baseline_value
    cfg = _config()
    benchmark = json.loads(_read_result_file(cfg, "bench_results.json"))
    throughput = json.loads(_read_result_file(cfg, "tput_results.json"))
    accuracy = json.loads(_read_result_file(cfg, "mc_results.json"))
    value = {
        "hardware": {
            "gpu": "NVIDIA RTX PRO 6000 Blackwell",
            "vramGb": 96,
            "contextTokens": 32_768,
        },
        "latency": sorted(
            (
                {
                    "promptTokens": int(prompt_tokens),
                    "ttftMs": result["ttft_ms"],
                    "decodeTps": result["decode_tps"],
                    "prefillTps": result["prefill_tps"],
                }
                for prompt_tokens, result in benchmark.items()
            ),
            key=lambda result: result["promptTokens"],
        ),
        "throughput": [
            {
                "concurrency": result["concurrency"],
                "aggregateDecodeTps": result["agg_decode_tps"],
                "perStreamTps": result["per_stream_tps"],
                "medianTtftMs": result["median_ttft_ms"],
                "endToEndTps": result["e2e_tps"],
            }
            for result in throughput
        ],
        "accuracy": [
            {
                "task": result["task"],
                "correct": result["correct"],
                "total": result["total"],
                "accuracy": result["acc"],
                "unparsed": result["unparsed"],
            }
            for result in accuracy
        ],
    }
    _baseline_value = value
    _baseline_expires = now + 60
    return value


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_stream_ticket(sandbox: str, ttl_seconds: int = 300) -> str:
    payload = json.dumps(
        {
            "sandbox": _validate_sandbox(sandbox),
            "exp": int(time.time()) + ttl_seconds,
            "nonce": secrets.token_urlsafe(12),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    encoded = _b64encode(payload)
    signature = hmac.new(
        _require_secret("GTZ_STREAM_SIGNING_KEY").encode(), encoded.encode(), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_stream_ticket(ticket: str, sandbox: str) -> None:
    try:
        encoded, supplied = ticket.split(".", 1)
        expected = hmac.new(
            _require_secret("GTZ_STREAM_SIGNING_KEY").encode(),
            encoded.encode(),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _b64decode(supplied)):
            raise ValueError("invalid signature")
        payload = json.loads(_b64decode(encoded))
        if payload.get("sandbox") != sandbox or int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired or mismatched ticket")
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ApiError(401, "Invalid or expired stream ticket") from error


async def require_api_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = _require_secret("GTZ_API_TOKEN")
    prefix = "Bearer "
    supplied = (
        authorization[len(prefix) :] if authorization and authorization.startswith(prefix) else ""
    )
    if not hmac.compare_digest(expected, supplied):
        raise ApiError(401, "Unauthorized")


async def _provision_project(project: str, objective: str) -> None:
    try:
        cfg = _config().model_copy(update={"project": project})
        agents = await Registry(_client(cfg), project).list_agents()
        main = next((agent for agent in agents if agent.role == "main"), None)
        if main:
            with Store() as store:
                store.upsert_project(project, objective=objective, status="running")
                store.upsert_agent(
                    main.sandbox_name,
                    project=project,
                    team=main.team,
                    name=main.agent,
                    role=main.role,
                )
            return
        await run_gtz("start", objective, "--project", project, timeout=1_800)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 -- failure is persisted for the UI.
        with Store() as store:
            store.set_project_status(project, "failed", str(error)[:1_000])


def _history() -> dict[str, list[dict[str, Any]]]:
    with Store() as store:
        projects = [
            dict(row)
            for row in store.db.execute(
                "SELECT * FROM projects WHERE status NOT IN ('deleting','deleted') "
                "ORDER BY created_at DESC"
            ).fetchall()
        ]
        agents = [
            dict(row)
            for row in store.db.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
        ]
    return {"projects": projects, "agents": agents}


def _sse(data: dict[str, Any], event_id: str | None = None) -> bytes:
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}data: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def _event_id(event: dict[str, Any]) -> str | None:
    if event.get("type") not in {"snapshot", "delta"}:
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    runtime_id = data.get("runtime_id")
    cursor = data.get("cursor")
    return f"{runtime_id}:{cursor}" if runtime_id and isinstance(cursor, int) else None


async def _agent_stream(
    request: Request,
    sandbox: str,
    after: int,
    runtime_id: str | None,
):
    persistent_runtime: dict[str, Any] | None = None
    if after == 0:
        with Store() as store:
            initial = store.conversation_for(sandbox)
            if store.is_persistent_agent(sandbox):
                persistent_runtime = initial["runtime"]
        if initial["turns"] or initial["events"] or initial["runtime_id"]:
            data = {
                "runtime_id": initial["runtime_id"],
                "session_id": initial["runtime"].get("session_id"),
                "turns": initial["turns"],
                "events": initial["events"],
                "cursor": initial["cursor"],
            }
            yield _sse(
                {"type": "snapshot", "data": data},
                f"{initial['runtime_id']}:{initial['cursor']}" if initial["runtime_id"] else None,
            )
            after = int(initial["cursor"])
            runtime_id = str(initial["runtime_id"] or "") or runtime_id

    if persistent_runtime is None:
        with Store() as store:
            if store.is_persistent_agent(sandbox):
                persistent_runtime = store.runtime_for(sandbox)
    if persistent_runtime is not None:
        yield _sse({"type": "connection", "data": {"mode": "live"}})
        yield _sse(
            {
                "type": "status",
                "data": {
                    "running": bool(persistent_runtime.get("running", True)),
                    "provisioning": False,
                    "log_mtime": time.time(),
                    "turn_status": persistent_runtime.get("turn_status", "running"),
                    "active_turn_id": persistent_runtime.get("active_turn_id"),
                    "queued": int(persistent_runtime.get("queued", 0)),
                    "cursor": int(persistent_runtime.get("cursor", after)),
                    "session_id": persistent_runtime.get("session_id"),
                    "runtime_id": persistent_runtime.get("runtime_id"),
                },
            }
        )
        while not await request.is_disconnected():
            yield _sse({"type": "heartbeat", "data": {"at": datetime.now(UTC).isoformat()}})
            await asyncio.sleep(5)
        return

    args = ["watch", sandbox, "--after", str(after)]
    if runtime_id:
        args.extend(["--runtime-id", runtime_id])
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "groktimizer.cli.main",
        *args,
        cwd=_command_cwd(),
        env=os.environ.copy(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    yield _sse({"type": "connection", "data": {"mode": "live"}})
    try:
        if process.stdout is None:
            raise RuntimeError("agent stream did not expose stdout")
        while not await request.is_disconnected():
            line = await process.stdout.readline()
            if not line:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                yield _sse({"type": "error", "data": {"message": "Invalid control-plane event"}})
                continue
            if isinstance(event, dict):
                yield _sse(event, _event_id(event))
    finally:
        await _terminate_process(process)


def create_app() -> FastAPI:
    project_tasks: dict[str, asyncio.Task[None]] = {}

    def schedule_project(project: str, objective: str) -> None:
        current = project_tasks.get(project)
        if current and not current.done():
            return
        task = asyncio.create_task(_provision_project(project, objective))
        project_tasks[project] = task

        def finished(done: asyncio.Task[None]) -> None:
            project_tasks.pop(project, None)
            with suppress(asyncio.CancelledError, Exception):
                done.result()

        task.add_done_callback(finished)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _require_secret("GTZ_API_TOKEN")
        _require_secret("GTZ_STREAM_SIGNING_KEY")
        _public_url()
        _config()
        with Store() as store:
            pending = [
                (row["name"], row["objective"])
                for row in store.list_projects()
                if row["status"] == "provisioning" and row["objective"]
            ]
        for project, objective in pending:
            schedule_project(project, objective)
        yield
        tasks = list(project_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(
        title="Groktimizer Control Plane",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, error: ApiError):
        body: dict[str, Any] = {"error": error.message}
        if error.code:
            body["code"] = error.code
        return JSONResponse(body, status_code=error.status)

    @app.get("/healthz")
    async def healthz():
        try:
            cfg = _config()
            with Store() as store:
                store.db.execute("SELECT 1").fetchone()
            _require_secret("GTZ_API_TOKEN")
            _require_secret("GTZ_STREAM_SIGNING_KEY")
        except Exception as error:  # noqa: BLE001 -- readiness must always return JSON.
            return JSONResponse({"ok": False, "error": str(error)}, status_code=503)
        return {
            "ok": True,
            "version": APP_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "project": cfg.project,
        }

    authenticated = [Depends(require_api_token)]

    @app.get("/v1/control-plane", dependencies=authenticated)
    async def control_plane():
        baseline_task = asyncio.to_thread(load_baseline)
        snapshot_task = run_gtz("snapshot", timeout=60)
        baseline_result, snapshot_result = await asyncio.gather(
            baseline_task, snapshot_task, return_exceptions=True
        )
        baseline = baseline_result if isinstance(baseline_result, dict) else EMPTY_BASELINE
        if isinstance(snapshot_result, Exception):
            return {
                "connected": False,
                "mode": "baseline",
                "reason": "The control plane is unavailable",
                "baseline": baseline,
            }
        try:
            snapshot = json.loads(snapshot_result)
        except json.JSONDecodeError:
            return {
                "connected": False,
                "mode": "baseline",
                "reason": "The control plane returned invalid data",
                "baseline": baseline,
            }
        return {"connected": True, "snapshot": snapshot, "baseline": baseline}

    @app.get("/v1/projects/history", dependencies=authenticated)
    async def project_history():
        return await asyncio.to_thread(_history)

    @app.post("/v1/projects", status_code=202, dependencies=authenticated)
    async def start_project(body: ProjectRequest):
        project = _validate_project(body.project)
        objective = body.objective.strip()
        if not objective:
            raise ApiError(400, "Objective must contain 1–8,000 characters")
        with Store() as store:
            if not store.upsert_project(
                project,
                objective=objective,
                status="provisioning",
                revive_deleted=True,
            ):
                raise ApiError(409, "Project is currently being deleted")
        schedule_project(project, objective)
        return {
            "started": True,
            "project": project,
            "sandbox": f"gtz-{project}-hq-main",
            "state": "provisioning",
        }

    @app.delete("/v1/projects/{project}", dependencies=authenticated)
    async def delete_project(project: str):
        project = _validate_project(project)
        task = project_tasks.get(project)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        with Store() as store:
            if not any(row["name"] == project for row in store.list_projects()):
                raise ApiError(404, "Project is not attached to this control plane")
        try:
            return _last_json(await run_gtz("delete", project, timeout=180))
        except CommandError as error:
            raise ApiError(502, "Project deletion failed") from error

    @app.delete("/v1/agents/{sandbox}", dependencies=authenticated)
    async def delete_agent(sandbox: str):
        sandbox = _validate_sandbox(sandbox)
        try:
            result = _last_json(await run_gtz("kill", sandbox, timeout=90))
        except CommandError as error:
            raise ApiError(502, "Agent teardown failed") from error
        return {"deleted": True, "sandbox": sandbox, **result}

    @app.post("/v1/agents/{sandbox}/messages", dependencies=authenticated)
    async def send_message(sandbox: str, body: MessageRequest):
        sandbox = _validate_sandbox(sandbox)
        message = body.message.strip()
        if not message:
            raise ApiError(400, "Message must contain 1–4,000 characters")
        if body.mode not in {"queue", "interrupt"}:
            raise ApiError(400, "Mode must be queue or interrupt")
        args = ["send", sandbox, message, "--client-id", body.client_id]
        if body.mode == "interrupt":
            args.append("--interrupt")
        if body.retry:
            args.append("--retry")
        try:
            parsed = _last_json(await run_gtz(*args, timeout=150))
        except CommandError as error:
            detail = str(error)
            if "runner is unavailable" in detail or "repair the sandbox" in detail:
                raise ApiError(
                    409,
                    "The agent runner needs repair before this message can be delivered.",
                    "runner_unavailable",
                ) from error
            raise ApiError(
                504 if error.timed_out else 502,
                "Delivery could not be confirmed. Retrying is safe and will reuse the "
                "same message id."
                if error.timed_out
                else "Steering delivery could not be confirmed.",
                "delivery_unknown",
            ) from error
        return {
            "sent": True,
            "id": parsed["id"],
            "turnId": parsed["turn_id"],
            "status": parsed["status"],
            "mode": parsed["mode"],
            "turn": parsed["turn"],
        }

    @app.post("/v1/agents/{sandbox}/interrupt", dependencies=authenticated)
    async def interrupt_agent(sandbox: str):
        sandbox = _validate_sandbox(sandbox)
        try:
            return _last_json(await run_gtz("interrupt-chat", sandbox, timeout=45))
        except CommandError as error:
            raise ApiError(502, "The active response could not be stopped") from error

    @app.post("/v1/agents/{sandbox}/repair", dependencies=authenticated)
    async def repair_agent(sandbox: str):
        sandbox = _validate_sandbox(sandbox)
        try:
            return _last_json(await run_gtz("repair-chat", sandbox, timeout=900))
        except CommandError as error:
            raise ApiError(502, "Agent repair failed") from error

    @app.post("/v1/agents/{sandbox}/stream-ticket", dependencies=authenticated)
    async def stream_ticket(sandbox: str, body: StreamTicketRequest):
        sandbox = _validate_sandbox(sandbox)
        ticket = issue_stream_ticket(sandbox)
        query: dict[str, str] = {"ticket": ticket, "after": str(body.after)}
        if body.runtime_id:
            query["runtime_id"] = body.runtime_id
        url = f"{_public_url()}/v1/agents/{sandbox}/stream?{urllib.parse.urlencode(query)}"
        return {"url": url, "expiresIn": 300}

    @app.get("/v1/agents/{sandbox}/stream")
    async def stream_agent(
        request: Request,
        sandbox: str,
        ticket: str,
        after: int = 0,
        runtime_id: str | None = None,
    ):
        sandbox = _validate_sandbox(sandbox)
        if after < 0:
            raise ApiError(400, "Invalid stream cursor")
        verify_stream_ticket(ticket, sandbox)
        return StreamingResponse(
            _agent_stream(request, sandbox, after, runtime_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "groktimizer.api:app",
        host=os.environ.get("GTZ_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("GTZ_API_PORT", "8080")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("GTZ_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        access_log=False,
    )


if __name__ == "__main__":
    main()
