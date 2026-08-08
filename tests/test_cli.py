import pytest

from groktimizer.cli.main import collect_snapshot, format_tree, start_main_orchestrator
from groktimizer.config import Config
from groktimizer.core.registry import AgentInfo
from groktimizer.core.sandbox import ExecResult, agent_labels
from tests.fakes import FakeSandboxClient


def test_format_tree():
    agents = [
        AgentInfo("demo", "hq", "main", "main", "gtz-demo-hq-main"),
        AgentInfo("demo", "attn", "lead", "team", "gtz-demo-attn-lead"),
        AgentInfo("demo", "attn", "impl-1", "implementer", "gtz-demo-attn-impl-1"),
    ]
    out = format_tree(agents)
    assert out.index("main") < out.index("attn") < out.index("impl-1")


async def test_collect_snapshot_is_json_safe():
    client = FakeSandboxClient()
    await client.create(
        "gtz-demo-hq-main",
        "image",
        "region",
        agent_labels("demo", "hq", "main", "main"),
        {},
    )
    await client.create(
        "gtz-demo-attn-lead",
        "image",
        "region",
        agent_labels("demo", "attn", "lead", "team"),
        {},
    )
    client.exec_responses["tmux has-session"] = ExecResult("running\n1723123456\n", 0)
    cfg = Config(
        project="demo",
        shared_repo="git@example.com/work.git",
        tooling_repo="git@example.com/tools.git",
    )

    snapshot = await collect_snapshot(cfg, client)

    assert snapshot["project"] == "demo"
    assert [agent["role"] for agent in snapshot["agents"]] == ["main", "team"]
    assert all(agent["running"] is True for agent in snapshot["agents"])
    assert snapshot["agents"][1]["branch"] == "team/attn"
    assert snapshot["caps"]["max_teams"] == 5
    assert set(snapshot["integrations"]) == {"blaxel", "runpod", "xai", "github"}


async def test_start_main_orchestrator_refuses_duplicate():
    client = FakeSandboxClient()
    await client.create(
        "gtz-demo-hq-main",
        "image",
        "region",
        agent_labels("demo", "hq", "main", "main"),
        {},
    )
    cfg = Config(
        project="demo",
        shared_repo="git@example.com/work.git",
        tooling_repo="git@example.com/tools.git",
    )

    with pytest.raises(ValueError, match="already exists"):
        await start_main_orchestrator(cfg, client, "brief", {})


async def test_project_cap_blocks_third_project(tmp_path):
    from groktimizer.core.store import Store

    client = FakeSandboxClient()
    await client.create("gtz-alpha-hq-main", "img", "r",
                        agent_labels("alpha", "hq", "main", "main"), {})
    await client.create("gtz-beta-hq-main", "img", "r",
                        agent_labels("beta", "hq", "main", "main"), {})
    cfg = Config(project="gamma", shared_repo="git@x:y.git", tooling_repo="https://g/o/r.git")
    with Store(tmp_path / "gtz.db") as store:
        with pytest.raises(ValueError, match="active project cap"):
            await start_main_orchestrator(cfg, client, "brief", {}, store)


async def test_snapshot_ingests_into_store(tmp_path):
    from groktimizer.core.store import Store

    client = FakeSandboxClient()
    await client.create("gtz-demo-hq-main", "img", "r",
                        agent_labels("demo", "hq", "main", "main"), {})
    client.exec_responses["tail -n"] = ExecResult(
        stdout='{"id":"steer-9","role":"user","body":"hi","at":"2026-01-01T00:00:00"}\n',
        exit_code=0,
    )
    client.exec_responses["wc -c"] = ExecResult(stdout="0", exit_code=0)
    cfg = Config(project="demo", shared_repo="git@x:y.git", tooling_repo="https://g/o/r.git")
    with Store(tmp_path / "gtz.db") as store:
        await collect_snapshot(cfg, client, store)
        assert store.list_projects()[0]["name"] == "demo"
        assert store.list_agents("demo")[0]["sandbox"] == "gtz-demo-hq-main"
        assert store.messages_for("gtz-demo-hq-main")[0]["id"] == "steer-9"
