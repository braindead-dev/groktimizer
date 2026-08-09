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
    assert projects[0]["status"] == "running"
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


def turn(status="queued"):
    return {
        "id": "turn-1",
        "client_id": "client-1",
        "prompt": "full prompt",
        "display_prompt": "go",
        "mode": "queue",
        "sender_kind": "operator",
        "sender_sandbox": None,
        "sender_label": "You",
        "status": status,
        "created_at": "2026-01-01T00:00:00",
        "started_at": None,
        "finished_at": None,
        "error": None,
        "revision": 1,
    }


def test_structured_turns_and_events(store):
    store.upsert_agent("sb", project="demo", team="hq", name="main", role="main")
    assert store.upsert_turns("sb", [turn()]) == 1
    assert (
        store.insert_turn_events(
            "sb",
            [
                {
                    "id": "event-1",
                    "seq": 1,
                    "turn_id": "turn-1",
                    "type": "assistant_text",
                    "payload": {"text": "done"},
                    "at": "2026-01-01T00:00:01",
                }
            ],
        )
        == 1
    )
    updated = turn("completed")
    updated["finished_at"] = "2026-01-01T00:00:02"
    store.upsert_turns("sb", [updated])
    store.set_event_cursor("sb", 1)
    store.set_runtime("sb", {"turn_status": "idle", "queued": 0})

    conversation = store.conversation_for("sb")
    assert conversation["turns"][0]["status"] == "completed"
    assert conversation["events"][0]["payload"] == {"text": "done"}
    assert conversation["cursor"] == 1
    assert conversation["runtime"]["turn_status"] == "idle"


def test_turn_status_cannot_regress_from_an_older_revision(store):
    store.upsert_agent("sb", project="demo", team="hq", name="main", role="main")
    completed = turn("completed")
    completed["revision"] = 4
    completed["finished_at"] = "2026-01-01T00:00:02"
    store.upsert_turns("sb", [completed])
    stale = turn("running")
    stale["revision"] = 2
    store.upsert_turns("sb", [stale])
    saved = store.conversation_for("sb")["turns"][0]
    assert saved["status"] == "completed"
    assert saved["revision"] == 4


def test_store_rejects_an_unversioned_existing_schema(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    sqlite3.connect(path).execute("CREATE TABLE legacy(value TEXT)").connection.close()
    with pytest.raises(RuntimeError, match="unsupported store schema"):
        Store(path)
