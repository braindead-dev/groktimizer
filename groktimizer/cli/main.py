"""gtz — human operator CLI. Thin wrappers over core; config from ./groktimizer.toml."""
import asyncio
import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from groktimizer.config import Config, load_config

load_dotenv()  # pick up BL_/RUNPOD_/XAI_ keys from ./.env before any command runs
from groktimizer.core import monitor
from groktimizer.core.bootstrap import PASSTHROUGH_ENVS, spawn_agent
from groktimizer.core.gpu import BudgetedRunPod
from groktimizer.core.registry import AgentInfo, Registry
from groktimizer.core.sandbox import MAIN_TEAM

app = typer.Typer(no_args_is_help=True)


def _cfg() -> Config:
    return load_config(Path("groktimizer.toml"))


def _client(cfg: Config):
    from groktimizer.core.blaxel_client import BlaxelSandboxClient
    return BlaxelSandboxClient(cfg.region)


def format_tree(agents: list[AgentInfo]) -> str:
    lines = []
    for a in sorted(agents, key=lambda a: (a.team != MAIN_TEAM, a.team, a.role != "team", a.agent)):
        indent = "" if a.team == MAIN_TEAM else ("  " if a.role == "team" else "    ")
        label = a.team if a.role == "team" else a.agent
        lines.append(f"{indent}{label} [{a.role}] ({a.sandbox_name})")
    return "\n".join(lines)


@app.command()
def start(brief: str):
    """Spawn the main orchestrator with a research brief."""
    cfg = _cfg()
    envs = {k: v for k in PASSTHROUGH_ENVS if (v := os.environ.get(k))}
    name = asyncio.run(spawn_agent(cfg, _client(cfg), team=MAIN_TEAM, agent="main",
                                   role="main", brief=brief, extra_envs=envs))
    typer.echo(f"main orchestrator started: {name}")


@app.command()
def tree():
    """Show all teams and agents."""
    cfg = _cfg()
    agents = asyncio.run(Registry(_client(cfg), cfg.project).list_agents())
    typer.echo(format_tree(agents) or "(no agents)")


@app.command()
def tail(sandbox: str, lines: int = 50):
    """Tail an agent's session log."""
    cfg = _cfg()
    typer.echo(asyncio.run(monitor.tail_log(_client(cfg), sandbox, lines)))


@app.command()
def send(sandbox: str, message: str):
    """Send a steering message to an agent."""
    cfg = _cfg()
    asyncio.run(monitor.send_message(_client(cfg), sandbox, message))
    typer.echo("sent")


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
    """Tear down every sandbox in the project."""
    cfg = _cfg()
    client = _client(cfg)

    async def _stop():
        agents = await Registry(client, cfg.project).list_agents()
        for a in agents:
            await client.delete(a.sandbox_name)
        return len(agents)

    typer.echo(f"deleted {asyncio.run(_stop())} sandboxes")


if __name__ == "__main__":
    app()
