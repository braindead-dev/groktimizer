"""gtz — human operator CLI. Thin wrappers over core; config from ./groktimizer.toml."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import typer
from dotenv import load_dotenv

from groktimizer.config import Config, load_config
from groktimizer.core import monitor
from groktimizer.core.bootstrap import PASSTHROUGH_ENVS, spawn_agent
from groktimizer.core.gpu import BudgetedRunPod
from groktimizer.core.ingest import ingest_agent
from groktimizer.core.registry import AgentInfo, Registry, active_projects
from groktimizer.core.sandbox import MAIN_TEAM, branch_name
from groktimizer.core.store import Store

load_dotenv()  # pick up BL_/RUNPOD_/XAI_ keys from ./.env before any command runs

app = typer.Typer(no_args_is_help=True)


def _cfg() -> Config:
    return load_config(Path("groktimizer.toml"))


def _client(cfg: Config):
    from groktimizer.core.blaxel_client import BlaxelSandboxClient

    return BlaxelSandboxClient(cfg.region)


def _require_project_sandbox(cfg: Config, sandbox: str) -> None:
    if not sandbox.startswith(f"gtz-{cfg.project}-"):
        raise typer.BadParameter("sandbox does not belong to the configured project")


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
    live_projects = await active_projects(client)
    if cfg.project not in live_projects and len(live_projects) >= cfg.caps.max_active_projects:
        raise ValueError(
            f"active project cap reached ({cfg.caps.max_active_projects}): "
            f"{', '.join(live_projects)} — stop one first"
        )
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
        store.upsert_project(cfg.project, objective=brief)
        store.upsert_agent(name, project=cfg.project, team=MAIN_TEAM,
                           name="main", role="main")
    return name


async def collect_snapshot(cfg: Config, client, store: Store | None = None) -> dict:
    """Return a JSON-safe control-plane snapshot for operator UIs.

    When a store is given, the snapshot poll doubles as the ingestion heartbeat:
    project/agent rows are upserted and new chat + log deltas are persisted.
    """
    agents = await Registry(client, cfg.project).list_agents()
    if store is not None:
        store.upsert_project(cfg.project)
        await asyncio.gather(
            *(ingest_agent(store, client, agent) for agent in agents),
            return_exceptions=True,
        )
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
            }
        )
    return {
        "project": cfg.project,
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
        "agents": serialized_agents,
    }


async def watch_agent(
    client, sandbox: str, interval: float = 1.0, lines: int = 80,
    store: Store | None = None, agent_info: AgentInfo | None = None,
) -> None:
    """Emit newline-delimited JSON snapshots for an SSE bridge."""
    previous_log: str | None = None
    previous_status: dict | None = None
    previous_messages: list[dict[str, str]] | None = None
    last_heartbeat = 0.0
    while True:
        if store is not None and agent_info is not None:
            await ingest_agent(store, client, agent_info)
        status, log, messages = await asyncio.gather(
            monitor.agent_status(client, sandbox),
            monitor.tail_log(client, sandbox, lines),
            monitor.tail_messages(client, sandbox, lines),
        )
        if status != previous_status:
            print(json.dumps({"type": "status", "data": status}), flush=True)
            previous_status = status
        if log != previous_log:
            print(json.dumps({"type": "log", "data": {"content": log}}), flush=True)
            previous_log = log
        if messages != previous_messages:
            print(
                json.dumps({"type": "messages", "data": {"messages": messages}}),
                flush=True,
            )
            previous_messages = messages
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
def start(brief: str):
    """Spawn the main orchestrator with a research brief."""
    cfg = _cfg()
    envs = {k: v for k in PASSTHROUGH_ENVS if (v := os.environ.get(k))}
    try:
        with Store() as store:
            name = asyncio.run(start_main_orchestrator(cfg, _client(cfg), brief, envs, store))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
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
    """Tail an agent's session log."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
    typer.echo(asyncio.run(monitor.tail_log(_client(cfg), sandbox, lines)))


@app.command()
def watch(sandbox: str, interval: float = 1.0, lines: int = 80):
    """Stream an agent's status and rolling log as newline-delimited JSON."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
    client = _client(cfg)

    async def _watch(store: Store) -> None:
        agents = await Registry(client, cfg.project).list_agents()
        agent_info = next((a for a in agents if a.sandbox_name == sandbox), None)
        await watch_agent(client, sandbox, interval=interval, lines=lines,
                          store=store, agent_info=agent_info)

    try:
        with Store() as store:
            asyncio.run(_watch(store))
    except KeyboardInterrupt:
        pass


@app.command()
def send(sandbox: str, message: str):
    """Send a steering message to an agent. Prints {"sent": true, "id": ...}."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
    message_id = asyncio.run(monitor.send_message(_client(cfg), sandbox, message))
    with Store() as store:
        store.insert_messages([{
            "id": message_id, "sandbox": sandbox, "role": "user",
            "body": message, "at": datetime.now(UTC).isoformat(),
        }])
    typer.echo(json.dumps({"sent": True, "id": message_id}))


@app.command()
def spend():
    """Show GPU spend (local ledger mirror; authoritative ledger lives with the agents)."""
    import runpod as rp

    cfg = _cfg()
    rp.api_key = os.environ["RUNPOD_API_KEY"]
    gpus = BudgetedRunPod(rp, cfg.budget, Path(".gtz/ledger.json"))
    typer.echo(f"live pods: {list(gpus.ledger['live'])}")
    typer.echo(f"spend: ${gpus.current_spend_usd():.2f} / ${cfg.budget.spend_ceiling_usd:.2f}")


@app.command()
def stop():
    """Tear down every sandbox in the project. History stays in the store."""
    cfg = _cfg()
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
        typer.echo(f"deleted {asyncio.run(_stop(store))} sandboxes")


@app.command()
def kill(sandbox: str):
    """Delete a single agent's sandbox. Its history stays in the store."""
    cfg = _cfg()
    _require_project_sandbox(cfg, sandbox)
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
    typer.echo(json.dumps({"deleted": True, "sandbox": sandbox}))


if __name__ == "__main__":
    app()
