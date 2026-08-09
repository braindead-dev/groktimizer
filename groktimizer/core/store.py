"""Durable SQLite mirror for projects, agents, turns, and structured events."""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  name       TEXT PRIMARY KEY,
  objective  TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'provisioning',
  error      TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  stopped_at TEXT
);
CREATE TABLE IF NOT EXISTS agents (
  sandbox    TEXT PRIMARY KEY,
  project    TEXT NOT NULL,
  team       TEXT NOT NULL,
  name       TEXT NOT NULL,
  role       TEXT NOT NULL,
  created_at TEXT NOT NULL,
  terminated_at TEXT,
  runtime_id TEXT NOT NULL DEFAULT '',
  event_cursor INTEGER NOT NULL DEFAULT 0,
  runtime_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS turns (
  id             TEXT PRIMARY KEY,
  sandbox        TEXT NOT NULL,
  client_id      TEXT NOT NULL,
  prompt         TEXT NOT NULL,
  display_prompt TEXT NOT NULL,
  mode           TEXT NOT NULL,
  sender_kind    TEXT NOT NULL,
  sender_sandbox TEXT,
  sender_label   TEXT,
  status         TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  started_at     TEXT,
  finished_at    TEXT,
  error          TEXT,
  revision       INTEGER NOT NULL DEFAULT 0,
  UNIQUE(sandbox, client_id)
);
CREATE INDEX IF NOT EXISTS idx_turns_sandbox_created ON turns(sandbox, created_at, id);
CREATE TABLE IF NOT EXISTS turn_events (
  id         TEXT PRIMARY KEY,
  sandbox    TEXT NOT NULL,
  remote_seq INTEGER NOT NULL,
  turn_id    TEXT NOT NULL,
  type       TEXT NOT NULL,
  payload    TEXT NOT NULL,
  at         TEXT NOT NULL,
  UNIQUE(sandbox, remote_seq)
);
CREATE INDEX IF NOT EXISTS idx_turn_events_sandbox_seq
  ON turn_events(sandbox, remote_seq);
"""


def default_db_path() -> Path:
    return Path(os.environ.get("GTZ_DB", ".gtz/groktimizer.db"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        version = int(self.db.execute("PRAGMA user_version").fetchone()[0])
        existing = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()
        if existing and version != SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported store schema {version}; delete {self.path} "
                f"for schema {SCHEMA_VERSION}"
            )
        self.db.executescript(_SCHEMA)
        self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.db.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    # -- projects ---------------------------------------------------------

    def upsert_project(
        self, name: str, objective: str = "", status: str = "running", error: str | None = None
    ) -> None:
        timestamp = _now()
        with self.db:
            self.db.execute(
                "INSERT INTO projects (name, objective, status, error, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET"
                "   objective = CASE WHEN excluded.objective != '' THEN excluded.objective"
                "                    ELSE projects.objective END,"
                "   status = excluded.status, error = excluded.error,"
                "   updated_at = excluded.updated_at, stopped_at = NULL",
                (name, objective, status, error, timestamp, timestamp),
            )

    def set_project_status(self, name: str, status: str, error: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "UPDATE projects SET status=?, error=?, updated_at=? WHERE name=?",
                (status, error, _now(), name),
            )

    def mark_project_stopped(self, name: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE projects SET status='stopped', error=NULL, stopped_at=?, updated_at=? "
                "WHERE name=?",
                (_now(), _now(), name),
            )

    def list_projects(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM projects ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    # -- agents -----------------------------------------------------------

    def upsert_agent(self, sandbox: str, *, project: str, team: str, name: str, role: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO agents (sandbox, project, team, name, role, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(sandbox) DO UPDATE SET terminated_at = NULL",
                (sandbox, project, team, name, role, _now()),
            )

    def mark_agent_terminated(self, sandbox: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE agents SET terminated_at=? WHERE sandbox=? AND terminated_at IS NULL",
                (_now(), sandbox),
            )

    def list_agents(self, project: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM agents WHERE project=? ORDER BY created_at", (project,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_event_cursor(self, sandbox: str) -> int:
        row = self.db.execute(
            "SELECT event_cursor FROM agents WHERE sandbox=?", (sandbox,)
        ).fetchone()
        return int(row["event_cursor"]) if row else 0

    def set_event_cursor(self, sandbox: str, cursor: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE agents SET event_cursor=MAX(event_cursor, ?) WHERE sandbox=?",
                (cursor, sandbox),
            )

    def set_runtime(self, sandbox: str, runtime: dict) -> None:
        with self.db:
            self.db.execute(
                "UPDATE agents SET runtime_id=?, runtime_json=? WHERE sandbox=?",
                (
                    str(runtime.get("runtime_id") or ""),
                    json.dumps(runtime, separators=(",", ":")),
                    sandbox,
                ),
            )

    def runtime_for(self, sandbox: str) -> dict:
        row = self.db.execute(
            "SELECT runtime_json FROM agents WHERE sandbox=?", (sandbox,)
        ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(row["runtime_json"])
        except (json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def reset_conversation(self, sandbox: str, runtime_id: str = "") -> None:
        """Drop mirrored turns when a sandbox runtime database is recreated."""
        with self.db:
            self.db.execute("DELETE FROM turn_events WHERE sandbox=?", (sandbox,))
            self.db.execute("DELETE FROM turns WHERE sandbox=?", (sandbox,))
            self.db.execute(
                "UPDATE agents SET runtime_id=?, event_cursor=0, runtime_json='{}' WHERE sandbox=?",
                (runtime_id, sandbox),
            )

    # -- structured turns ------------------------------------------------

    def upsert_turns(self, sandbox: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        values = [
            {**row, "sandbox": sandbox, "revision": int(row.get("revision", 0))} for row in rows
        ]
        with self.db:
            before = self.db.total_changes
            self.db.executemany(
                "INSERT INTO turns(id, sandbox, client_id, prompt, display_prompt, mode, "
                "sender_kind, "
                "sender_sandbox, sender_label, status, created_at, started_at, "
                "finished_at, error, revision) "
                "VALUES(:id, :sandbox, :client_id, :prompt, :display_prompt, :mode, :sender_kind, "
                ":sender_sandbox, :sender_label, :status, :created_at, :started_at, "
                ":finished_at, :error, :revision) "
                "ON CONFLICT(id) DO UPDATE SET "
                "client_id=excluded.client_id, prompt=excluded.prompt, "
                "display_prompt=excluded.display_prompt, mode=excluded.mode, "
                "sender_kind=excluded.sender_kind, sender_sandbox=excluded.sender_sandbox, "
                "sender_label=excluded.sender_label, status=excluded.status, "
                "created_at=excluded.created_at, started_at=excluded.started_at, "
                "finished_at=excluded.finished_at, error=excluded.error, "
                "revision=excluded.revision "
                "WHERE excluded.revision >= turns.revision",
                values,
            )
            return self.db.total_changes - before

    def insert_turn_events(self, sandbox: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        values = [
            {
                "id": row["id"],
                "sandbox": sandbox,
                "remote_seq": row["seq"],
                "turn_id": row["turn_id"],
                "type": row["type"],
                "payload": json.dumps(row.get("payload", {}), separators=(",", ":")),
                "at": row["at"],
            }
            for row in rows
        ]
        with self.db:
            before = self.db.total_changes
            self.db.executemany(
                "INSERT OR IGNORE INTO turn_events"
                "(id, sandbox, remote_seq, turn_id, type, payload, at) "
                "VALUES(:id, :sandbox, :remote_seq, :turn_id, :type, :payload, :at)",
                values,
            )
            return self.db.total_changes - before

    def conversation_for(self, sandbox: str, limit: int = 200) -> dict:
        turns = [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM (SELECT * FROM turns WHERE sandbox=? "
                "ORDER BY created_at DESC, id DESC LIMIT ?) ORDER BY created_at, id",
                (sandbox, limit),
            ).fetchall()
        ]
        turn_ids = [turn["id"] for turn in turns]
        events: list[dict] = []
        if turn_ids:
            placeholders = ",".join("?" for _ in turn_ids)
            rows = self.db.execute(
                f"SELECT id, remote_seq AS seq, turn_id, type, payload, at "  # noqa: S608
                f"FROM turn_events WHERE sandbox=? AND turn_id IN ({placeholders}) "
                "ORDER BY remote_seq",
                (sandbox, *turn_ids),
            ).fetchall()
            for row in rows:
                event = dict(row)
                try:
                    event["payload"] = json.loads(event["payload"])
                except json.JSONDecodeError:
                    event["payload"] = {"text": event["payload"]}
                events.append(event)
        cursor = self.get_event_cursor(sandbox)
        row = self.db.execute(
            "SELECT runtime_id FROM agents WHERE sandbox=?", (sandbox,)
        ).fetchone()
        return {
            "turns": turns,
            "events": events,
            "cursor": cursor,
            "runtime_id": row["runtime_id"] if row else "",
            "runtime": self.runtime_for(sandbox),
        }
