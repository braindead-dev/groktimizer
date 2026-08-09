"""Durable SQLite mirror for projects, agents, turns, and structured events."""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  name       TEXT PRIMARY KEY,
  title      TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS research_documents (
  project        TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL,
  document_json  TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  FOREIGN KEY(project) REFERENCES projects(name) ON DELETE CASCADE
);
"""


def default_db_path() -> Path:
    return Path(os.environ.get("GTZ_DB", ".gtz/groktimizer.db"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def project_title(name: str, objective: str) -> str:
    """Return the stable display title persisted for a project."""
    cleaned = " ".join(objective.split())
    if cleaned:
        if len(cleaned) <= 32:
            return cleaned
        prefix = cleaned[:31].rstrip()
        if " " in prefix:
            prefix = prefix.rsplit(" ", 1)[0]
        return f"{prefix}…"
    return name.replace("-", " ").replace("_", " ").title()


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}  # noqa: S608


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        version = int(self.db.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            str(row["name"])
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        existing = bool(tables)
        legacy_tables = {"projects", "agents", "messages", "log_chunks"}
        if existing and version == 0 and legacy_tables.issubset(tables):
            self._backup_legacy_store(version)
            self._migrate_legacy_store()
        elif existing and version in {2, 3}:
            self._backup_legacy_store(version)
            with self.db:
                if version == 2:
                    self.db.execute(
                        "ALTER TABLE projects ADD COLUMN title TEXT NOT NULL DEFAULT ''"
                    )
                self.db.executescript(_SCHEMA)
                self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif existing and version != SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported store schema {version}; delete {self.path} "
                f"for schema {SCHEMA_VERSION}"
            )
        self.db.executescript(_SCHEMA)
        for row in self.db.execute(
            "SELECT name, objective FROM projects WHERE title=''"
        ).fetchall():
            self.db.execute(
                "UPDATE projects SET title=? WHERE name=?",
                (project_title(str(row["name"]), str(row["objective"])), row["name"]),
            )
        self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.db.commit()

    def _backup_legacy_store(self, version: int) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = self.path.with_name(f"{self.path.name}.schema-v{version}-{stamp}.bak")
        with sqlite3.connect(backup_path) as backup:
            self.db.backup(backup)

    def _migrate_legacy_store(self) -> None:
        """Upgrade the original unversioned store without discarding local history."""
        project_columns = _columns(self.db, "projects")
        agent_columns = _columns(self.db, "agents")
        with self.db:
            if "error" not in project_columns:
                self.db.execute("ALTER TABLE projects ADD COLUMN error TEXT")
            if "updated_at" not in project_columns:
                self.db.execute(
                    "ALTER TABLE projects ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
                )
                self.db.execute("UPDATE projects SET updated_at=created_at WHERE updated_at='' ")
            self.db.execute("UPDATE projects SET status='running' WHERE status='active'")
            if "title" not in project_columns:
                self.db.execute("ALTER TABLE projects ADD COLUMN title TEXT NOT NULL DEFAULT ''")

            if "runtime_id" not in agent_columns:
                self.db.execute("ALTER TABLE agents ADD COLUMN runtime_id TEXT NOT NULL DEFAULT ''")
            if "event_cursor" not in agent_columns:
                self.db.execute(
                    "ALTER TABLE agents ADD COLUMN event_cursor INTEGER NOT NULL DEFAULT 0"
                )
            if "runtime_json" not in agent_columns:
                self.db.execute(
                    "ALTER TABLE agents ADD COLUMN runtime_json TEXT NOT NULL DEFAULT '{}'"
                )

            self.db.executescript(_SCHEMA)
            has_messages = self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'"
            ).fetchone()
            if has_messages:
                self.db.execute(
                    "INSERT OR IGNORE INTO turns("
                    "id, sandbox, client_id, prompt, display_prompt, mode, sender_kind, "
                    "sender_sandbox, sender_label, status, created_at, started_at, finished_at, "
                    "error, revision) "
                    "SELECT id, sandbox, id, body, body, 'queue', 'operator', NULL, NULL, "
                    "'completed', at, NULL, at, NULL, 0 FROM messages WHERE role='user'"
                )
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    # -- projects ---------------------------------------------------------

    def upsert_project(
        self,
        name: str,
        objective: str = "",
        status: str = "running",
        error: str | None = None,
        *,
        revive_deleted: bool = False,
    ) -> bool:
        timestamp = _now()
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO projects "
                "(name, title, objective, status, error, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET"
                "   title = CASE WHEN excluded.objective != '' THEN excluded.title"
                "                WHEN projects.title = '' THEN excluded.title"
                "                ELSE projects.title END,"
                "   objective = CASE WHEN excluded.objective != '' THEN excluded.objective"
                "                    ELSE projects.objective END,"
                "   status = excluded.status, error = excluded.error,"
                "   updated_at = excluded.updated_at, stopped_at = NULL"
                " WHERE projects.status != 'deleting'"
                "   AND (projects.status != 'deleted' OR ?)",
                (
                    name,
                    project_title(name, objective),
                    objective,
                    status,
                    error,
                    timestamp,
                    timestamp,
                    revive_deleted,
                ),
            )
        return cursor.rowcount > 0

    def set_project_status(self, name: str, status: str, error: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "UPDATE projects SET status=?, error=?, updated_at=? WHERE name=?",
                (status, error, _now(), name),
            )

    def set_project_title(self, name: str, title: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE projects SET title=?, updated_at=? WHERE name=?",
                (title.strip(), _now(), name),
            )

    def mark_project_stopped(self, name: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE projects SET status='stopped', error=NULL, stopped_at=?, updated_at=? "
                "WHERE name=?",
                (_now(), _now(), name),
            )

    def begin_project_deletion(self, name: str) -> None:
        """Hide a project and block polling from re-ingesting it during teardown."""
        timestamp = _now()
        with self.db:
            self.db.execute(
                "INSERT INTO projects "
                "(name, title, objective, status, error, created_at, updated_at)"
                " VALUES (?, '', '', 'deleting', NULL, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET status='deleting', error=NULL,"
                " updated_at=excluded.updated_at",
                (name, timestamp, timestamp),
            )

    def delete_project(self, name: str) -> None:
        """Remove project activity while retaining a deletion tombstone."""
        with self.db:
            self.db.execute(
                "DELETE FROM turn_events WHERE sandbox IN "
                "(SELECT sandbox FROM agents WHERE project=?)",
                (name,),
            )
            self.db.execute(
                "DELETE FROM turns WHERE sandbox IN (SELECT sandbox FROM agents WHERE project=?)",
                (name,),
            )
            self.db.execute("DELETE FROM agents WHERE project=?", (name,))
            self.db.execute("DELETE FROM research_documents WHERE project=?", (name,))
            self.db.execute(
                "UPDATE projects SET title='', objective='', status='deleted', error=NULL,"
                " stopped_at=?, updated_at=? WHERE name=?",
                (_now(), _now(), name),
            )

    def recover_project_objective(self, name: str) -> str | None:
        """Recover a missing objective/title from the main agent's persisted kickoff turn."""
        row = self.db.execute(
            "SELECT turns.display_prompt FROM turns"
            " JOIN agents ON agents.sandbox=turns.sandbox"
            " WHERE agents.project=? AND agents.role='main'"
            " AND turns.sender_kind='system' AND TRIM(turns.display_prompt) != ''"
            " ORDER BY turns.created_at LIMIT 1",
            (name,),
        ).fetchone()
        if not row:
            return None
        objective = str(row["display_prompt"]).strip()
        with self.db:
            self.db.execute(
                "UPDATE projects SET objective=?, title=?, updated_at=?"
                " WHERE name=? AND objective='' AND status NOT IN ('deleting','deleted')",
                (objective, project_title(name, objective), _now(), name),
            )
        return objective

    def list_projects(self, *, include_deleted: bool = False) -> list[dict]:
        where = "" if include_deleted else "WHERE status NOT IN ('deleting','deleted')"
        rows = self.db.execute(
            f"SELECT * FROM projects {where} ORDER BY created_at"  # noqa: S608
        ).fetchall()
        return [dict(r) for r in rows]

    # -- validated research documents ------------------------------------

    def upsert_research_document(
        self, project: str, document_json: str, schema_version: int = 1
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO research_documents(project, schema_version, document_json, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(project) DO UPDATE SET"
                " schema_version=excluded.schema_version,"
                " document_json=excluded.document_json, updated_at=excluded.updated_at",
                (project, schema_version, document_json, _now()),
            )

    def research_document(self, project: str) -> dict | None:
        row = self.db.execute(
            "SELECT document_json FROM research_documents WHERE project=?", (project,)
        ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["document_json"])
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    def is_persistent_agent(self, sandbox: str) -> bool:
        return self.runtime_for(sandbox).get("transport") == "persistent"

    # -- agents -----------------------------------------------------------

    def upsert_agent(self, sandbox: str, *, project: str, team: str, name: str, role: str) -> bool:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO agents (sandbox, project, team, name, role, created_at)"
                " SELECT ?, ?, ?, ?, ?, ?"
                " WHERE EXISTS (SELECT 1 FROM projects WHERE name=?"
                " AND status NOT IN ('deleting','deleted'))"
                " ON CONFLICT(sandbox) DO UPDATE SET terminated_at = NULL",
                (sandbox, project, team, name, role, _now(), project),
            )
        return cursor.rowcount > 0

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

    def prepare_record_history(
        self,
        sandbox: str,
        turn_prefix: str,
        event_count: int,
        *,
        legacy_turn_ids: tuple[str, ...] = (),
    ) -> int:
        """Replace record-owned history while preserving and rebasing later live events."""
        prefix_length = len(turn_prefix)
        legacy = set(legacy_turn_ids)
        preserved = [
            row
            for row in self.db.execute(
                "SELECT id, turn_id FROM turn_events WHERE sandbox=?"
                " AND substr(turn_id, 1, ?) != ? ORDER BY remote_seq, id",
                (sandbox, prefix_length, turn_prefix),
            ).fetchall()
            if row["turn_id"] not in legacy
        ]
        with self.db:
            self.db.execute(
                "DELETE FROM turn_events WHERE sandbox=? AND substr(turn_id, 1, ?)=?",
                (sandbox, prefix_length, turn_prefix),
            )
            self.db.execute(
                "DELETE FROM turns WHERE sandbox=? AND substr(id, 1, ?)=?",
                (sandbox, prefix_length, turn_prefix),
            )
            if legacy_turn_ids:
                placeholders = ",".join("?" for _ in legacy_turn_ids)
                parameters = (sandbox, *legacy_turn_ids)
                self.db.execute(
                    f"DELETE FROM turn_events WHERE sandbox=? AND turn_id IN ({placeholders})",  # noqa: S608
                    parameters,
                )
                self.db.execute(
                    f"DELETE FROM turns WHERE sandbox=? AND id IN ({placeholders})",  # noqa: S608
                    parameters,
                )
            # Move preserved rows out of the positive sequence range first. Updating
            # directly can collide with another preserved row's current sequence.
            for temporary, row in enumerate(preserved, start=1):
                self.db.execute(
                    "UPDATE turn_events SET remote_seq=? WHERE id=? AND sandbox=?",
                    (-temporary, row["id"], sandbox),
                )
            for offset, row in enumerate(preserved, start=event_count + 1):
                self.db.execute(
                    "UPDATE turn_events SET remote_seq=? WHERE id=? AND sandbox=?",
                    (offset, row["id"], sandbox),
                )
            cursor = event_count + len(preserved)
            self.db.execute(
                "UPDATE agents SET event_cursor=? WHERE sandbox=?",
                (cursor, sandbox),
            )
        return cursor

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
