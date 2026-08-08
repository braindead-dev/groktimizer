# groktimizer/core/registry.py
"""Live agent registry: Blaxel sandbox labels are the source of truth."""

from dataclasses import dataclass

from groktimizer.config import Caps
from groktimizer.core.sandbox import MAIN_TEAM, Role, SandboxClient


class CapExceededError(Exception):
    pass


@dataclass
class AgentInfo:
    project: str
    team: str
    agent: str
    role: Role
    sandbox_name: str


async def active_projects(client: SandboxClient) -> list[str]:
    """Distinct project names that currently have any live agent sandbox."""
    metas = await client.list({})
    return sorted({
        project for m in metas
        if (project := m.labels.get("gtz-project"))
    })


class Registry:
    def __init__(self, client: SandboxClient, project: str):
        self.client = client
        self.project = project

    async def list_agents(self, team: str | None = None) -> list[AgentInfo]:
        labels = {"gtz-project": self.project}
        if team:
            labels["gtz-team"] = team
        metas = await self.client.list(labels)
        return [
            AgentInfo(
                project=self.project,
                team=m.labels["gtz-team"],
                agent=m.labels["gtz-agent"],
                role=m.labels["gtz-role"],  # type: ignore[arg-type]
                sandbox_name=m.name,
            )
            for m in metas
        ]

    async def list_teams(self) -> list[str]:
        agents = await self.list_agents()
        return sorted({a.team for a in agents} - {MAIN_TEAM})

    async def ensure_can_spawn(
        self, role: Role, team: str, caps: Caps, agent: str | None = None
    ) -> None:
        if role == "main":
            raise CapExceededError("the main orchestrator is spawned by the CLI, not by agents")
        teams = await self.list_teams()
        members = await self.list_agents(team=team)
        if agent is not None and any(a.agent == agent for a in members):
            raise CapExceededError(f"agent name {agent!r} already exists in team {team!r}")
        if role == "team":
            if team in teams:
                raise CapExceededError(f"team {team!r} already has an orchestrator")
            if len(teams) >= caps.max_teams:
                raise CapExceededError(f"team cap reached ({caps.max_teams})")
        if role == "implementer":
            implementers = [a for a in members if a.role == "implementer"]
            if len(implementers) >= caps.max_agents_per_team:
                raise CapExceededError(
                    f"implementer cap reached for team {team!r} ({caps.max_agents_per_team})"
                )
