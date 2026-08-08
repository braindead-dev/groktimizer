from pathlib import Path

import pytest

from groktimizer.core.store import Store


@pytest.fixture
def store(tmp_path: Path):
    with Store(tmp_path / "gtz.db") as s:
        yield s


def test_project_lifecycle(store):
    store.upsert_project("demo", objective="Make it fast")
    store.upsert_project("demo", objective="Make it fast")  # idempotent
    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["status"] == "active"
    assert projects[0]["objective"] == "Make it fast"
    store.mark_project_stopped("demo")
    assert store.list_projects()[0]["status"] == "stopped"
    assert store.list_projects()[0]["stopped_at"] is not None
    # re-upserting an existing project must not clobber objective with empty default
    store.upsert_project("demo")
    assert store.list_projects()[0]["objective"] == "Make it fast"


def test_agent_lifecycle(store):
    store.upsert_agent(
        "gtz-demo-attn-impl1", project="demo", team="attn", name="impl1", role="implementer"
    )
    store.upsert_agent(
        "gtz-demo-attn-impl1", project="demo", team="attn", name="impl1", role="implementer"
    )
    agents = store.list_agents("demo")
    assert len(agents) == 1
    store.mark_agent_terminated("gtz-demo-attn-impl1")
    assert store.list_agents("demo")[0]["terminated_at"] is not None


def test_messages_dedup_and_order(store):
    rows = [
        {
            "id": "steer-1",
            "sandbox": "sb",
            "role": "user",
            "body": "hi",
            "at": "2026-01-01T00:00:00",
        },
        {
            "id": "reply-1",
            "sandbox": "sb",
            "role": "agent",
            "body": "yo",
            "at": "2026-01-01T00:00:01",
        },
    ]
    assert store.insert_messages(rows) == 2
    assert store.insert_messages(rows) == 0  # dedup by id
    messages = store.messages_for("sb")
    assert [m["id"] for m in messages] == ["steer-1", "reply-1"]
    assert messages[1]["role"] == "agent"


def test_log_chunks_and_offset(store):
    assert store.get_log_offset("sb") == 0
    store.upsert_agent("sb", project="demo", team="hq", name="main", role="main")
    store.append_log_chunk("sb", "line1\nline2\n", at="2026-01-01T00:00:00")
    store.set_log_offset("sb", 12)
    assert store.get_log_offset("sb") == 12
    assert "line1" in store.log_tail("sb", max_chars=1000)


def test_log_tail_bounded(store):
    store.upsert_agent("sb", project="demo", team="hq", name="main", role="main")
    for i in range(10):
        store.append_log_chunk("sb", f"chunk-{i}\n", at="2026-01-01T00:00:00")
    tail = store.log_tail("sb", max_chars=20)
    assert len(tail) <= 20
    assert "chunk-9" in tail
