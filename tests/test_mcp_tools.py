"""Integration-level gating tests: build the real FastMCP server per role and call
tools through it. Denials fire before any network/SDK call, so no mocking needed."""

import os

import pytest

from groktimizer.config import Config

CFG = Config(project="demo", shared_repo="git@x:y.git", tooling_repo="https://g/o/r.git")


def make_server(role: str, team: str):
    os.environ.update(
        {
            "GTZ_CONFIG_JSON": CFG.model_dump_json(),
            "GTZ_ROLE": role,
            "GTZ_TEAM": team,
            "GTZ_AGENT": "x",
        }
    )
    os.environ.pop("RUNPOD_API_KEY", None)
    from groktimizer.mcp.server import build_server

    return build_server()


async def test_tool_roster():
    server = make_server("main", "hq")
    tools = {t.name for t in await server.list_tools()}
    assert tools == {
        "list_teams",
        "list_agents",
        "spawn_agent",
        "dispatch_reconciler",
        "agent_status",
        "tail_agent",
        "exec_in_agent",
        "send_to_agent",
        "terminate_agent",
        "provision_gpu",
        "list_pods",
        "terminate_pod",
    }


async def test_implementer_cannot_spawn_or_manage():
    server = make_server("implementer", "attn")
    with pytest.raises(Exception, match="may not spawn"):
        await server.call_tool(
            "spawn_agent",
            {"team": "attn", "agent": "friend", "role_": "implementer", "brief": "b"},
        )
    with pytest.raises(Exception, match="own team"):
        await server.call_tool("terminate_agent", {"sandbox": "gtz-demo-attn-impl9"})
    with pytest.raises(Exception, match="only the main orchestrator"):
        await server.call_tool("dispatch_reconciler", {"brief": "b"})


async def test_team_orch_confined_to_own_team():
    server = make_server("team", "attn")
    with pytest.raises(Exception, match="own team"):
        await server.call_tool("exec_in_agent", {"sandbox": "gtz-demo-gemm-impl1", "command": "id"})
    with pytest.raises(Exception, match="own team"):
        await server.call_tool(
            "spawn_agent",
            {"team": "gemm", "agent": "impl1", "role_": "implementer", "brief": "b"},
        )
    with pytest.raises(Exception, match="not an agent sandbox of project"):
        await server.call_tool("terminate_agent", {"sandbox": "gtz-otherproj-attn-impl1"})


async def test_reconciler_readonly_and_no_control():
    server = make_server("reconciler", "hq")
    # control tools denied
    with pytest.raises(Exception, match="own team"):
        await server.call_tool("terminate_agent", {"sandbox": "gtz-demo-attn-impl1"})
    with pytest.raises(Exception, match="own team"):
        await server.call_tool("send_to_agent", {"sandbox": "gtz-demo-attn-impl1", "message": "hi"})
    with pytest.raises(Exception, match="may not spawn"):
        await server.call_tool(
            "spawn_agent",
            {"team": "attn", "agent": "a", "role_": "implementer", "brief": "b"},
        )


async def test_hyphenated_spawn_rejected_at_tool_layer():
    server = make_server("main", "hq")
    with pytest.raises(Exception, match="no hyphens"):
        await server.call_tool(
            "spawn_agent",
            {"team": "attn-opt", "agent": "a1", "role_": "implementer", "brief": "b"},
        )
