from pathlib import Path

import pytest

from groktimizer.core.store import Store


@pytest.fixture
def store(tmp_path: Path):
    with Store(tmp_path / "gtz.db") as s:
        s.upsert_project("demo")
        yield s


def test_project_lifecycle(store):
    store.upsert_project("demo", objective="Make it fast")
    store.upsert_project("demo", objective="Make it fast")  # idempotent
    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["status"] == "running"
    assert projects[0]["objective"] == "Make it fast"
    assert projects[0]["title"] == "Make it fast"
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


def test_delete_project_removes_agents_and_conversations(store):
    store.upsert_project("demo", objective="Make it fast")
    store.upsert_agent("sb", project="demo", team="attn", name="impl1", role="implementer")
    store.upsert_turns("sb", [turn()])
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
    store.delete_project("demo")
    assert store.list_projects() == []
    assert store.list_agents("demo") == []
    assert store.conversation_for("sb")["turns"] == []


def test_deletion_tombstone_blocks_concurrent_reingestion(store):
    store.begin_project_deletion("demo")
    assert store.list_projects() == []
    assert store.upsert_project("demo", status="running") is False
    assert store.upsert_agent(
        "sb", project="demo", team="hq", name="main", role="main"
    ) is False
    store.delete_project("demo")
    assert store.list_projects(include_deleted=True)[0]["status"] == "deleted"
    assert store.upsert_project(
        "demo", objective="A new run", status="provisioning", revive_deleted=True
    ) is True
    assert store.list_projects()[0]["title"] == "A new run"


def test_missing_objective_is_recovered_from_main_kickoff(store):
    store.upsert_agent("sb", project="demo", team="hq", name="main", role="main")
    kickoff = turn()
    kickoff["sender_kind"] = "system"
    kickoff["display_prompt"] = "Optimize attention throughput without quality loss"
    store.upsert_turns("sb", [kickoff])
    assert store.recover_project_objective("demo") == kickoff["display_prompt"]
    project = store.list_projects()[0]
    assert project["objective"] == kickoff["display_prompt"]
    assert project["title"] == "Optimize attention throughput…"


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


def test_store_migrates_original_unversioned_schema(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE projects (
              name TEXT PRIMARY KEY, objective TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, stopped_at TEXT
            );
            CREATE TABLE agents (
              sandbox TEXT PRIMARY KEY, project TEXT NOT NULL, team TEXT NOT NULL,
              name TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL,
              terminated_at TEXT, log_offset INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE messages (
              id TEXT PRIMARY KEY, sandbox TEXT NOT NULL, role TEXT NOT NULL,
              body TEXT NOT NULL, at TEXT NOT NULL
            );
            CREATE TABLE log_chunks (
              id INTEGER PRIMARY KEY AUTOINCREMENT, sandbox TEXT NOT NULL,
              content TEXT NOT NULL, at TEXT NOT NULL
            );
            INSERT INTO projects VALUES ('demo', 'Make it fast', 'active', '2026-01-01', NULL);
            INSERT INTO agents VALUES (
              'gtz-demo-hq-main', 'demo', 'hq', 'main', 'main', '2026-01-01', NULL, 0
            );
            INSERT INTO messages VALUES (
              'message-1', 'gtz-demo-hq-main', 'user', 'Try batching', '2026-01-02'
            );
            """
        )

    with Store(path) as migrated:
        assert migrated.db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert migrated.list_projects()[0]["status"] == "running"
        assert migrated.list_projects()[0]["updated_at"] == "2026-01-01"
        assert migrated.conversation_for("gtz-demo-hq-main")["turns"][0]["prompt"] == "Try batching"
        assert migrated.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'"
        ).fetchone()
    assert len(list(tmp_path.glob("legacy.db.schema-v0-*.bak"))) == 1


def test_store_migrates_v2_titles_without_losing_projects(tmp_path):
    import sqlite3

    path = tmp_path / "v2.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE projects (
              name TEXT PRIMARY KEY, objective TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'provisioning', error TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, stopped_at TEXT
            );
            INSERT INTO projects VALUES (
              'demo', 'Make inference faster', 'running', NULL,
              '2026-01-01', '2026-01-01', NULL
            );
            PRAGMA user_version=2;
            """
        )

    with Store(path) as migrated:
        project = migrated.list_projects()[0]
        assert project["objective"] == "Make inference faster"
        assert project["title"] == "Make inference faster"
        assert migrated.db.execute("PRAGMA user_version").fetchone()[0] == 3
    assert len(list(tmp_path.glob("v2.db.schema-v2-*.bak"))) == 1


def test_store_rejects_an_unknown_unversioned_schema(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    sqlite3.connect(path).execute("CREATE TABLE legacy(value TEXT)").connection.close()
    with pytest.raises(RuntimeError, match="unsupported store schema"):
        Store(path)
