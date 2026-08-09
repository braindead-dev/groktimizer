"""gtz — human operator CLI. Thin wrappers over core; config from ./groktimizer.toml."""

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import typer
from dotenv import load_dotenv

from groktimizer.config import Config, load_config
from groktimizer.core import monitor
from groktimizer.core.bootstrap import PASSTHROUGH_ENVS, spawn_agent
from groktimizer.core.gpu import BudgetedRunPod
from groktimizer.core.ingest import ingest_agent
from groktimizer.core.registry import AgentInfo, Registry
from groktimizer.core.sandbox import MAIN_TEAM, branch_name
from groktimizer.core.store import Store

load_dotenv()  # pick up BL_/RUNPOD_/XAI_ keys from ./.env before any command runs

app = typer.Typer(no_args_is_help=True)


def _cfg() -> Config:
    return load_config(Path("groktimizer.toml"))


def _client(cfg: Config):
    from groktimizer.core.blaxel_client import BlaxelSandboxClient

    return BlaxelSandboxClient(cfg.region)


def _sandbox_project(sandbox: str) -> str:
    match = re.fullmatch(
        r"gtz-(?P<project>[a-z0-9]{1,24})-[a-z0-9]{1,24}-[a-z0-9-]{1,24}",
        sandbox,
    )
    if not match:
        raise typer.BadParameter("invalid groktimizer sandbox name")
    return match.group("project")


def _require_project_sandbox(cfg: Config, sandbox: str) -> None:
    _sandbox_project(sandbox)


def format_tree(agents: list[AgentInfo]) -> str:
    lines = []
    for a in sorted(agents, key=lambda a: (a.team != MAIN_TEAM, a.team, a.role != "team", a.agent)):
        indent = "" if a.team == MAIN_TEAM else ("  " if a.role == "team" else "    ")
        label = a.team if a.role == "team" else a.agent
        lines.append(f"{indent}{label} [{a.role}] ({a.sandbox_name})")
    return "\n".join(lines)


async def start_main_orchestrator(
    cfg: Config, client, brief: str, envs: dict[str, str], store: Store | None = None
) -> str:
    """Provision the one main orchestrator allowed for a project."""
    agents = await Registry(client, cfg.project).list_agents()
    if any(agent.role == "main" for agent in agents):
        raise ValueError(f"main orchestrator already exists for project {cfg.project}")
    name = await spawn_agent(
        cfg,
        client,
        team=MAIN_TEAM,
        agent="main",
        role="main",
        brief=brief,
        extra_envs=envs,
    )
    if store is not None:
        store.upsert_project(cfg.project, objective=brief, status="running")
        store.upsert_agent(name, project=cfg.project, team=MAIN_TEAM, name="main", role="main")
    return name


async def collect_snapshot(cfg: Config, client, store: Store | None = None) -> dict:
    """Return a JSON-safe control-plane snapshot for operator UIs.

    The store is the durable record: the snapshot poll registers live sandboxes
    into it, ingests structured turn deltas, and marks agents whose sandbox has
    disappeared as terminated. Blaxel only answers "what is alive right now";
    an agent's code lives in the shared repo, linked by its branch pointer.
    """
    metas = await client.list({})
    agents = [
        AgentInfo(
            project=meta.labels["gtz-project"],
            team=meta.labels["gtz-team"],
            agent=meta.labels["gtz-agent"],
            role=meta.labels["gtz-role"],  # type: ignore[arg-type]
            sandbox_name=meta.name,
        )
        for meta in metas
        if all(
            isinstance(meta.labels.get(key), str) and meta.labels.get(key)
            for key in ("gtz-project", "gtz-team", "gtz-agent", "gtz-role")
        )
    ]
    ingest_errors: dict[str, str] = {}
    if store is not None:
        known_projects = {project["name"] for project in store.list_projects()}
        for project_name in {agent.project for agent in agents} - known_projects:
            store.upsert_project(project_name, status="running")
        ingest_results = await asyncio.gather(
            *(ingest_agent(store, client, agent) for agent in agents),
        )
        ingest_errors = {
            agent.sandbox_name: result
            for agent, result in zip(agents, ingest_results, strict=True)
            if result
        }
        live = {agent.sandbox_name for agent in agents}
        for project in store.list_projects():
            for row in store.list_agents(project["name"]):
                if row["terminated_at"] is None and row["sandbox"] not in live:
                    store.mark_agent_terminated(row["sandbox"])
    status_results = await asyncio.gather(
        *(monitor.agent_status(client, agent.sandbox_name) for agent in agents),
        return_exceptions=True,
    )
    serialized_agents = []
    for agent, result in zip(agents, status_results, strict=True):
        status = result if isinstance(result, dict) else {"running": False, "log_mtime": None}
        serialized_agents.append(
            {
                "project": agent.project,
                "team": agent.team,
                "agent": agent.agent,
                "role": agent.role,
                "sandbox_name": agent.sandbox_name,
                "branch": branch_name(agent.team, agent.agent, agent.role),
                "running": bool(status.get("running")),
                "log_mtime": status.get("log_mtime"),
                "turn_status": status.get("turn_status", "idle"),
                "active_turn_id": status.get("active_turn_id"),
                "queued": status.get("queued", 0),
                "session_id": status.get("session_id"),
                "runtime_id": status.get("runtime_id"),
                "ingest_error": ingest_errors.get(agent.sandbox_name),
            }
        )
    stored_projects: dict[str, dict] = {}
    if store is not None:
        stored_projects = {project["name"]: project for project in store.list_projects()}
    project_names = set(stored_projects) | {agent.project for agent in agents} | {cfg.project}
    projects = []
    for project_name in sorted(project_names):
        project_agents = [agent for agent in serialized_agents if agent["project"] == project_name]
        stored_project = stored_projects.get(project_name)
        projects.append(
            {
                "project": project_name,
                "project_state": {
                    "status": stored_project["status"]
                    if stored_project
                    else ("running" if project_agents else "idle"),
                    "objective": stored_project["objective"] if stored_project else "",
                    "error": stored_project["error"] if stored_project else None,
                },
                "agents": project_agents,
            }
        )
    configured = next(project for project in projects if project["project"] == cfg.project)
    return {
        "project": cfg.project,
        "project_state": configured["project_state"],
        "generated_at": datetime.now(UTC).isoformat(),
        "caps": cfg.caps.model_dump(),
        "budget": {
            "spend_ceiling_usd": cfg.budget.spend_ceiling_usd,
            "max_concurrent_pods": cfg.budget.max_concurrent_pods,
        },
        "research": {
            "target_gain_pct": cfg.research.target_gain_pct,
            "max_accuracy_loss_pct": cfg.research.max_accuracy_loss_pct,
        },
        "integrations": {
            "blaxel": bool(os.environ.get("BL_API_KEY") and os.environ.get("BL_WORKSPACE")),
            "runpod": bool(os.environ.get("RUNPOD_API_KEY")),
            "xai": bool(os.environ.get("XAI_API_KEY") or os.environ.get("XAI_API_KEY_2")),
            "github": bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")),
        },
        "agents": configured["agents"],
        "projects": projects,
    }


async def watch_agent(
    client,
    sandbox: str,
    interval: float = 1.0,
    lines: int = 80,
    after: int = 0,
    expected_runtime_id: str | None = None,
) -> None:
    """Emit a server-authoritative conversation snapshot followed by ordered deltas."""
    previous_log: str | None = None
    previous_status: dict | None = None
    cursor = max(0, after)
    first_runtime = True
    snapshot_required = cursor == 0
    last_heartbeat = 0.0
    while True:
        status, log, runtime = await asyncio.gather(
            monitor.agent_status(client, sandbox),
            monitor.tail_log(client, sandbox, lines),
            monitor.runtime_snapshot(client, sandbox, after=cursor),
        )
        if runtime:
            runtime_id = str(runtime.get("runtime_id") or "")
            if first_runtime and expected_runtime_id and runtime_id != expected_runtime_id:
                cursor = 0
                snapshot_required = True
                runtime = await monitor.runtime_snapshot(client, sandbox, after=0)
                runtime_id = str(runtime.get("runtime_id") or "") if runtime else ""
            if not runtime:
                await asyncio.sleep(max(interval, 0.25))
                continue
            events = runtime.get("events", [])
            next_cursor = max(cursor, int(runtime.get("cursor", cursor)))
            if first_runtime or events:
                print(
                    json.dumps(
                        {
                            "type": "snapshot" if snapshot_required else "delta",
                            "data": {
                                "runtime_id": runtime_id,
                                "session_id": runtime.get("session_id"),
                                "events": events,
                                "turns": runtime.get("turns", []),
                                "cursor": next_cursor,
                            },
                        }
                    ),
                    flush=True,
                )
            cursor = next_cursor
            first_runtime = False
            snapshot_required = False
        if status != previous_status:
            print(json.dumps({"type": "status", "data": status}), flush=True)
            previous_status = status
        if log != previous_log:
            print(json.dumps({"type": "log", "data": {"content": log}}), flush=True)
            previous_log = log
        now = asyncio.get_running_loop().time()
        if now - last_heartbeat >= 5:
            print(
                json.dumps(
                    {
                        "type": "heartbeat",
                        "data": {"at": datetime.now(UTC).isoformat()},
                    }
                ),
                flush=True,
            )
            last_heartbeat = now
        await asyncio.sleep(max(interval, 0.25))


@app.command()
def start(brief: str, project: str | None = typer.Option(None, "--project")):
    """Spawn the main orchestrator with a research brief."""
    cfg = _cfg()
    if project:
        cfg = cfg.model_copy(update={"project": project})
    envs = {k: v for k in PASSTHROUGH_ENVS if (v := os.environ.get(k))}
    with Store() as store:
        store.upsert_project(cfg.project, objective=brief, status="provisioning")
        try:
            name = asyncio.run(start_main_orchestrator(cfg, _client(cfg), brief, envs, store))
        except Exception as error:
            if isinstance(error, ValueError) and "already exists" in str(error):
                store.set_project_status(cfg.project, "running")
            else:
                store.set_project_status(cfg.project, "failed", str(error))
            if isinstance(error, ValueError):
                raise typer.BadParameter(str(error)) from error
            raise
    typer.echo(f"main orchestrator started: {name}")


@app.command()
def tree():
    """Show all teams and agents."""
    cfg = _cfg()
    agents = asyncio.run(Registry(_client(cfg), cfg.project).list_agents())
    typer.echo(format_tree(agents) or "(no agents)")


@app.command()
def snapshot():
    """Print a machine-readable snapshot of live teams and agents (and ingest history)."""
    cfg = _cfg()
    with Store() as store:
        data = asyncio.run(collect_snapshot(cfg, _client(cfg), store))
    typer.echo(json.dumps(data, separators=(",", ":")))


@app.command()
def tail(sandbox: str, lines: int = 50):
    """Tail an agent runner's diagnostic log."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
    typer.echo(asyncio.run(monitor.tail_log(_client(cfg), sandbox, lines)))


@app.command()
def watch(
    sandbox: str,
    interval: float = 1.0,
    lines: int = 80,
    after: int = 0,
    runtime_id: str | None = typer.Option(None, "--runtime-id"),
):
    """Stream structured agent events as newline-delimited JSON."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
    client = _client(cfg)

    try:
        asyncio.run(
            watch_agent(
                client,
                sandbox,
                interval=interval,
                lines=lines,
                after=after,
                expected_runtime_id=runtime_id,
            )
        )
    except KeyboardInterrupt:
        pass


@app.command()
def send(
    sandbox: str,
    message: str,
    interrupt: bool = typer.Option(False, "--interrupt", help="Interrupt the active turn"),
    client_id: str | None = typer.Option(None, "--client-id"),
    retry: bool = typer.Option(False, "--retry", help="Requeue this id only if its turn failed"),
):
    """Queue a steering message, or interrupt the active turn explicitly."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
    result = asyncio.run(
        monitor.send_message(
            _client(cfg),
            sandbox,
            message,
            mode="interrupt" if interrupt else "queue",
            client_id=client_id,
            retry=retry,
        )
    )
    typer.echo(
        json.dumps(
            {
                "sent": True,
                "id": result["client_id"],
                "turn_id": result["id"],
                "status": result["status"],
                "mode": result["mode"],
                "turn": result,
            }
        )
    )


@app.command("repair-chat")
def repair_chat(sandbox: str):
    """Non-destructively install the queued chat runner into an existing sandbox."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
    result = asyncio.run(monitor.repair_runtime(_client(cfg), sandbox))
    typer.echo(json.dumps(result, separators=(",", ":")))


@app.command()
def spend():
    """Show GPU spend (local ledger mirror; authoritative ledger lives with the agents)."""
    import runpod as rp

    cfg = _cfg()
    rp.api_key = os.environ["RUNPOD_API_KEY"]
    gpus = BudgetedRunPod(rp, cfg.budget, Path(".gtz/ledger.json"))
    typer.echo(f"live pods: {list(gpus.ledger['live'])}")
    typer.echo(f"spend: ${gpus.current_spend_usd():.2f} / ${cfg.budget.spend_ceiling_usd:.2f}")


def _sweep_project_pods(name_prefix: str) -> list[str]:
    """Terminate orphan-prone RunPod pods by name prefix. Never raises."""
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        return []
    try:
        import runpod as rp

        from groktimizer.core.gpu import sweep_pods

        rp.api_key = api_key
        return sweep_pods(rp, name_prefix)
    except Exception:  # noqa: BLE001 — cleanup is best effort
        return []


@app.command()
def stop(project: str | None = typer.Option(None, "--project")):
    """Tear down every sandbox in the project and sweep its RunPod pods.

    History stays in the store."""
    cfg = _cfg()
    if project:
        cfg = cfg.model_copy(update={"project": project})
    client = _client(cfg)

    async def _stop(store: Store):
        agents = await Registry(client, cfg.project).list_agents()
        for a in agents:
            await ingest_agent(store, client, a)  # final capture before teardown
            await client.delete(a.sandbox_name)
            store.mark_agent_terminated(a.sandbox_name)
        store.mark_project_stopped(cfg.project)
        return len(agents)

    with Store() as store:
        deleted = asyncio.run(_stop(store))
    swept = _sweep_project_pods(f"gtz-{cfg.project}-")
    typer.echo(f"deleted {deleted} sandboxes; terminated {len(swept)} runpod pods")


@app.command()
def kill(sandbox: str):
    """Delete a single agent's sandbox and sweep its RunPod pods.

    Its history stays in the store."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
    cfg = cfg.model_copy(update={"project": _sandbox_project(sandbox)})
    client = _client(cfg)

    async def _kill(store: Store):
        agents = await Registry(client, cfg.project).list_agents()
        agent_info = next((a for a in agents if a.sandbox_name == sandbox), None)
        if agent_info is not None:
            await ingest_agent(store, client, agent_info)
        await client.delete(sandbox)
        store.mark_agent_terminated(sandbox)

    with Store() as store:
        asyncio.run(_kill(store))
    swept = _sweep_project_pods(f"{sandbox}-")
    typer.echo(json.dumps({"deleted": True, "sandbox": sandbox, "pods_terminated": swept}))


if __name__ == "__main__":
    app()
