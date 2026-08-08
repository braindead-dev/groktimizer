# tests/test_registry.py
import pytest

from groktimizer.config import Caps
from groktimizer.core.registry import AgentInfo, CapExceededError, Registry
from groktimizer.core.sandbox import agent_labels, sandbox_name
from tests.fakes import FakeSandboxClient


async def seed(client, project, team, agent, role):
    await client.create(
        sandbox_name(project, team, agent),
        "img",
        "r",
        agent_labels(project, team, agent, role),
        {},
    )


@pytest.fixture
def client():
    return FakeSandboxClient()


async def test_list_teams_and_agents(client):
    await seed(client, "demo", "hq", "main", "main")
    await seed(client, "demo", "attn", "lead", "team")
    await seed(client, "demo", "attn", "impl-1", "implementer")
    await seed(client, "other", "x", "lead", "team")  # different project: excluded
    reg = Registry(client, "demo")
    assert await reg.list_teams() == ["attn"]  # hq is not a real team
    agents = await reg.list_agents(team="attn")
    assert {a.agent for a in agents} == {"lead", "impl-1"}
    assert all(isinstance(a, AgentInfo) for a in agents)


async def test_team_cap(client):
    caps = Caps(max_teams=1, max_agents_per_team=5)
    await seed(client, "demo", "attn", "lead", "team")
    reg = Registry(client, "demo")
    with pytest.raises(CapExceededError):
        await reg.ensure_can_spawn("team", "gemm", caps)
    # spawning into the EXISTING team's implementer slots is still fine
    await reg.ensure_can_spawn("implementer", "attn", caps)


async def test_agent_cap(client):
    caps = Caps(max_teams=10, max_agents_per_team=1)
    await seed(client, "demo", "attn", "impl-1", "implementer")
    reg = Registry(client, "demo")
    with pytest.raises(CapExceededError):
        await reg.ensure_can_spawn("implementer", "attn", caps)


async def test_duplicate_agent_name(client):
    caps = Caps()
    await seed(client, "demo", "attn", "impl-1", "implementer")
    reg = Registry(client, "demo")
    with pytest.raises(CapExceededError, match="already exists"):
        await reg.ensure_can_spawn("implementer", "attn", caps, agent="impl-1")
    await reg.ensure_can_spawn("implementer", "attn", caps, agent="impl-2")
