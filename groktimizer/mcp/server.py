"""MCP server every agent runs; tools are gated by the agent's own role."""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from groktimizer.config import Config
from groktimizer.core import monitor
from groktimizer.core.bootstrap import PASSTHROUGH_ENVS, spawn_agent
from groktimizer.core.gpu import BudgetedRunPod
from groktimizer.core.registry import Registry
from groktimizer.core.sandbox import MAIN_TEAM, ROLES, Role, validate_name


class PermissionError_(Exception):
    pass


def check_spawn(*, actor_role: Role, actor_team: str, target_role: Role, target_team: str) -> None:
    if target_role not in ROLES:
        raise PermissionError_(f"unknown role {target_role!r}; valid roles: {ROLES}")
    if actor_role == "main":
        if target_role == "main":
            raise PermissionError_("cannot spawn another main orchestrator")
        return
    if actor_role == "team":
        if target_role != "implementer" or target_team != actor_team:
            raise PermissionError_(
                "team orchestrators may only spawn implementers in their own team"
            )
        return
    raise PermissionError_("implementers and the reconciler may not spawn agents")


def check_manage(
    *, actor_role: Role, actor_team: str, target_team: str, readonly: bool = False
) -> None:
    if actor_role == "main":
        return
    if actor_role == "team" and target_team == actor_team:
        return
    if actor_role == "reconciler" and readonly:
        return  # the reconciler may observe any agent to recover context, never control
    raise PermissionError_("you may only manage agents in your own team")


def build_server() -> FastMCP:
    import runpod as rp

    from groktimizer.core.blaxel_client import BlaxelSandboxClient

    cfg = Config.model_validate_json(os.environ["GTZ_CONFIG_JSON"])
    role: Role = os.environ["GTZ_ROLE"]  # type: ignore[assignment]
    my_team = os.environ["GTZ_TEAM"]
    rp.api_key = os.environ.get("RUNPOD_API_KEY", "")  # GPU tools fail per-call if unset

    client = BlaxelSandboxClient(cfg.region)
    registry = Registry(client, cfg.project)
    gpus = BudgetedRunPod(rp, cfg.budget, Path("/var/lib/gtz/ledger.json"))
    mcp = FastMCP("groktimizer")

    def _team_of(sandbox: str) -> str:
        # gtz-{project}-{team}-{agent}; safe because validate_name bans hyphens
        # in team/agent names, and management is confined to this project's prefix.
        prefix = f"gtz-{cfg.project}-"
        if not sandbox.startswith(prefix):
            raise PermissionError_(
                f"{sandbox!r} is not an agent sandbox of project {cfg.project!r}"
            )
        return sandbox.removeprefix(prefix).split("-")[0]

    @mcp.tool()
    async def list_teams() -> list[str]:
        """List all team names in this project."""
        return await registry.list_teams()

    @mcp.tool()
    async def list_agents(team: str | None = None) -> list[dict]:
        """List agents (optionally within one team) with role and sandbox name."""
        return [vars(a) for a in await registry.list_agents(team)]

    @mcp.tool(name="spawn_agent")
    async def spawn_agent_tool(team: str, agent: str, role_: str, brief: str) -> str:
        """Spawn a subordinate agent. role_ is 'team' or 'implementer'; team and agent
        names must be lowercase alphanumeric (no hyphens). Spawning a 'team' role into a
        new team name creates that team (main orchestrator only)."""
        validate_name("team", team)
        validate_name("agent", agent)
        check_spawn(actor_role=role, actor_team=my_team, target_role=role_, target_team=team)  # type: ignore[arg-type]
        await registry.ensure_can_spawn(role_, team, cfg.caps, agent=agent)  # type: ignore[arg-type]
        envs = {k: v for k in PASSTHROUGH_ENVS if (v := os.environ.get(k))}
        return await spawn_agent(
            cfg,
            client,
            team=team,
            agent=agent,
            role=role_,
            brief=brief,
            extra_envs=envs,
        )  # type: ignore[arg-type]

    @mcp.tool()
    async def dispatch_reconciler(brief: str) -> str:
        """FINAL step of the research loop (main orchestrator only): dispatch the
        reconciliation agent. Give it a full summary of every approach tried and where
        each team's artifacts live. It merges the winning work into the shared repo's
        main branch, verifies benchmark + accuracy on real hardware, and writes
        FINAL_REPORT.md — when that lands, the research loop is done."""
        if role != "main":
            raise PermissionError_("only the main orchestrator may dispatch the reconciler")
        existing = await registry.list_agents(team=MAIN_TEAM)
        if any(a.agent == "reconciler" for a in existing):
            raise PermissionError_("a reconciler is already running; monitor it instead")
        envs = {k: v for k in PASSTHROUGH_ENVS if (v := os.environ.get(k))}
        return await spawn_agent(
            cfg,
            client,
            team=MAIN_TEAM,
            agent="reconciler",
            role="reconciler",
            brief=brief,
            extra_envs=envs,
        )

    @mcp.tool()
    async def agent_status(sandbox: str) -> dict:
        """Check whether a subordinate's grok session is alive and when it last logged."""
        check_manage(
            actor_role=role,
            actor_team=my_team,
            target_team=_team_of(sandbox),
            readonly=True,
        )
        return await monitor.agent_status(client, sandbox)

    @mcp.tool()
    async def tail_agent(sandbox: str, lines: int = 50) -> str:
        """Read the last N lines of a subordinate's session log."""
        check_manage(
            actor_role=role,
            actor_team=my_team,
            target_team=_team_of(sandbox),
            readonly=True,
        )
        return await monitor.tail_log(client, sandbox, lines)

    @mcp.tool()
    async def exec_in_agent(sandbox: str, command: str) -> str:
        """Run a shell command inside a subordinate's sandbox."""
        check_manage(actor_role=role, actor_team=my_team, target_team=_team_of(sandbox))
        return await monitor.exec_in_agent(client, sandbox, command)

    @mcp.tool()
    async def send_to_agent(sandbox: str, message: str) -> str:
        """Send a steering message to a subordinate (resumes its grok session)."""
        check_manage(actor_role=role, actor_team=my_team, target_team=_team_of(sandbox))
        await monitor.send_message(client, sandbox, message)
        return "sent"

    @mcp.tool()
    async def terminate_agent(sandbox: str) -> str:
        """Delete a subordinate's sandbox."""
        check_manage(actor_role=role, actor_team=my_team, target_team=_team_of(sandbox))
        await client.delete(sandbox)
        return "terminated"

    @mcp.tool()
    def provision_gpu(name: str, image: str, gpu_type: str) -> dict:
        """Provision a RunPod GPU pod (budget-enforced). Terminate it when done."""
        # Prefix with this agent's sandbox name so orphaned pods are attributable
        # and gtz stop/kill can sweep them even after the sandbox is gone.
        my_agent = os.environ.get("GTZ_AGENT", "unknown")
        pod_name = f"gtz-{cfg.project}-{my_team}-{my_agent}-{name}"
        return gpus.provision(pod_name, image, gpu_type)

    @mcp.tool()
    def list_pods() -> dict:
        """List live pods, current spend, and reap over-lifetime pods."""
        reaped = gpus.reap_expired()
        return {
            "live": gpus.ledger["live"],
            "spend_usd": gpus.current_spend_usd(),
            "reaped": reaped,
            "ceiling_usd": cfg.budget.spend_ceiling_usd,
        }

    @mcp.tool()
    def terminate_pod(pod_id: str) -> str:
        """Terminate a RunPod pod and record its cost."""
        gpus.terminate(pod_id)
        return "terminated"

    return mcp
