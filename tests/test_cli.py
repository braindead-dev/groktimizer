import json

import pytest
from typer import BadParameter

from groktimizer.cli.main import (
    _sandbox_project,
    collect_snapshot,
    format_tree,
    start_main_orchestrator,
)
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


def test_sandbox_project_supports_non_default_projects():
    assert _sandbox_project("gtz-latency123-hq-main") == "latency123"
    with pytest.raises(BadParameter, match="invalid groktimizer sandbox name"):
        _sandbox_project("other-project")


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
    assert snapshot["projects"][0]["project"] == "demo"
    assert set(snapshot["integrations"]) == {"blaxel", "runpod", "xai", "github"}


async def test_collect_snapshot_includes_multiple_projects():
    client = FakeSandboxClient()
    await client.create(
        "gtz-alpha-hq-main",
        "image",
        "region",
        agent_labels("alpha", "hq", "main", "main"),
        {},
    )
    await client.create(
        "gtz-beta-hq-main",
        "image",
        "region",
        agent_labels("beta", "hq", "main", "main"),
        {},
    )
    client.exec_responses["tmux has-session"] = ExecResult("running\n1723123456\n", 0)
    cfg = Config(
        project="alpha",
        shared_repo="git@example.com/work.git",
        tooling_repo="git@example.com/tools.git",
    )
    snapshot = await collect_snapshot(cfg, client)
    assert [project["project"] for project in snapshot["projects"]] == ["alpha", "beta"]
    assert snapshot["agents"][0]["project"] == "alpha"


async def test_snapshot_hides_tombstoned_project_during_concurrent_deletion(tmp_path):
    from groktimizer.core.store import Store

    client = FakeSandboxClient()
    await client.create(
        "gtz-deleted-hq-main",
        "image",
        "region",
        agent_labels("deleted", "hq", "main", "main"),
        {},
    )
    cfg = Config(
        project="active",
        shared_repo="git@example.com/work.git",
        tooling_repo="git@example.com/tools.git",
    )
    with Store(tmp_path / "gtz.db") as store:
        store.upsert_project("deleted")
        store.begin_project_deletion("deleted")
        snapshot = await collect_snapshot(cfg, client, store)
    assert [project["project"] for project in snapshot["projects"]] == ["active"]
    assert snapshot["agents"] == []


async def test_sql_only_running_project_is_reported_idle(tmp_path):
    from groktimizer.core.store import Store

    cfg = Config(
        project="demo",
        shared_repo="git@example.com/work.git",
        tooling_repo="git@example.com/tools.git",
    )
    with Store(tmp_path / "gtz.db") as store:
        store.upsert_project("demo", objective="Make inference faster", status="running")
        snapshot = await collect_snapshot(cfg, FakeSandboxClient(), store)
    state = snapshot["projects"][0]["project_state"]
    assert state["status"] == "idle"
    assert state["title"] == "Make inference faster"


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


async def test_project_count_does_not_block_another_configured_project():
    client = FakeSandboxClient()
    await client.create(
        "gtz-alpha-hq-main", "img", "r", agent_labels("alpha", "hq", "main", "main"), {}
    )
    await client.create(
        "gtz-beta-hq-main", "img", "r", agent_labels("beta", "hq", "main", "main"), {}
    )
    cfg = Config(project="gamma", shared_repo="git@x:y.git", tooling_repo="https://g/o/r.git")
    name = await start_main_orchestrator(cfg, client, "brief", {})
    assert name == "gtz-gamma-hq-main"


async def test_snapshot_ingests_into_store(tmp_path):
    from groktimizer.core.store import Store

    client = FakeSandboxClient()
    await client.create(
        "gtz-demo-hq-main", "img", "r", agent_labels("demo", "hq", "main", "main"), {}
    )
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout=json.dumps(
            {
                "session_id": "session-1",
                "runtime_id": "runtime-1",
                "cursor": 0,
                "active_turn_id": None,
                "turn_status": "idle",
                "queued": 0,
                "turns": [],
                "events": [],
            }
        )
        + "\n",
        exit_code=0,
    )
    cfg = Config(project="demo", shared_repo="git@x:y.git", tooling_repo="https://g/o/r.git")
    with Store(tmp_path / "gtz.db") as store:
        await collect_snapshot(cfg, client, store)
        assert store.list_projects()[0]["name"] == "demo"
        assert store.list_agents("demo")[0]["sandbox"] == "gtz-demo-hq-main"
        assert store.runtime_for("gtz-demo-hq-main")["session_id"] == "session-1"


async def test_snapshot_marks_vanished_agents_terminated(tmp_path):
    from groktimizer.core.store import Store

    client = FakeSandboxClient()
    await client.create(
        "gtz-demo-hq-main", "img", "r", agent_labels("demo", "hq", "main", "main"), {}
    )
    client.exec_responses["wc -c"] = ExecResult(stdout="0", exit_code=0)
    cfg = Config(project="demo", shared_repo="git@x:y.git", tooling_repo="https://g/o/r.git")
    with Store(tmp_path / "gtz.db") as store:
        store.upsert_project("demo")
        store.upsert_agent(
            "gtz-demo-attn-dead1", project="demo", team="attn", name="dead1", role="implementer"
        )
        await collect_snapshot(cfg, client, store)
        rows = {a["sandbox"]: a["terminated_at"] for a in store.list_agents("demo")}
        assert rows["gtz-demo-attn-dead1"] is not None  # vanished -> terminated
        assert rows["gtz-demo-hq-main"] is None  # live -> untouched
