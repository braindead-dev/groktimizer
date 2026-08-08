"""Durable SQLite store for projects, agents, chat messages, and session logs.

All writes go through gtz commands (single-writer discipline); the web UI reads
the file read-only. WAL mode keeps concurrent gtz processes safe.
"""

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  name       TEXT PRIMARY KEY,
  objective  TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
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
  log_offset INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
  id      TEXT PRIMARY KEY,
  sandbox TEXT NOT NULL,
  role    TEXT NOT NULL,
  body    TEXT NOT NULL,
  at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_sandbox_at ON messages(sandbox, at);
CREATE TABLE IF NOT EXISTS log_chunks (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  sandbox TEXT NOT NULL,
  content TEXT NOT NULL,
  at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_log_chunks_sandbox ON log_chunks(sandbox, id);
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
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    # -- projects ---------------------------------------------------------

    def upsert_project(self, name: str, objective: str = "") -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO projects (name, objective, status, created_at)"
                " VALUES (?, ?, 'active', ?)"
                " ON CONFLICT(name) DO UPDATE SET"
                "   objective = CASE WHEN excluded.objective != '' THEN excluded.objective"
                "                    ELSE projects.objective END,"
                "   status = 'active', stopped_at = NULL",
                (name, objective, _now()),
            )

    def mark_project_stopped(self, name: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE projects SET status='stopped', stopped_at=? WHERE name=?",
                (_now(), name),
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

    # -- messages ---------------------------------------------------------

    def insert_messages(self, rows: list[dict]) -> int:
        with self.db:
            before = self.db.total_changes
            self.db.executemany(
                "INSERT OR IGNORE INTO messages (id, sandbox, role, body, at)"
                " VALUES (:id, :sandbox, :role, :body, :at)",
                rows,
            )
            return self.db.total_changes - before

    def messages_for(self, sandbox: str, limit: int = 200) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, role, body, at FROM (SELECT * FROM messages WHERE sandbox=?"
            " ORDER BY at DESC, id DESC LIMIT ?) ORDER BY at, id",
            (sandbox, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- session logs -----------------------------------------------------

    def get_log_offset(self, sandbox: str) -> int:
        row = self.db.execute(
            "SELECT log_offset FROM agents WHERE sandbox=?", (sandbox,)
        ).fetchone()
        return int(row["log_offset"]) if row else 0

    def set_log_offset(self, sandbox: str, offset: int) -> None:
        with self.db:
            self.db.execute("UPDATE agents SET log_offset=? WHERE sandbox=?", (offset, sandbox))

    def append_log_chunk(self, sandbox: str, content: str, at: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO log_chunks (sandbox, content, at) VALUES (?, ?, ?)",
                (sandbox, content, at or _now()),
            )

    def log_tail(self, sandbox: str, max_chars: int = 16_000) -> str:
        rows = self.db.execute(
            "SELECT content FROM log_chunks WHERE sandbox=? ORDER BY id DESC LIMIT 50",
            (sandbox,),
        ).fetchall()
        text = "".join(r["content"] for r in reversed(rows))
        return text[-max_chars:]
