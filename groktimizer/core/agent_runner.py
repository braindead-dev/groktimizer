"""Sandbox-local queued turn runner for one Grok agent.

This file is intentionally standard-library only.  Bootstrap uploads it to
``/opt/gtz/agent_runner.py`` so existing sandboxes can be repaired without
depending on the version of the groktimizer wheel already installed there.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

DB_PATH = Path(os.environ.get("GTZ_RUNTIME_DB", "/var/lib/gtz/runtime.db"))
MAX_EVENT_TEXT = 64_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
  id             TEXT PRIMARY KEY,
  client_id      TEXT NOT NULL UNIQUE,
  prompt         TEXT NOT NULL,
  display_prompt TEXT NOT NULL,
  mode           TEXT NOT NULL,
  sender_kind    TEXT NOT NULL,
  sender_sandbox TEXT,
  sender_label   TEXT,
  status         TEXT NOT NULL,
  priority       INTEGER NOT NULL DEFAULT 10,
  created_at     TEXT NOT NULL,
  started_at     TEXT,
  finished_at    TEXT,
  error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_turns_queue
  ON turns(status, priority, created_at);
CREATE TABLE IF NOT EXISTS events (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,
  id       TEXT NOT NULL UNIQUE,
  turn_id  TEXT NOT NULL,
  type     TEXT NOT NULL,
  payload  TEXT NOT NULL,
  at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_turn_seq ON events(turn_id, seq);
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=5.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.executescript(SCHEMA)
    if not get_meta(db, "runtime_id"):
        set_meta(db, "runtime_id", f"runtime-{uuid4().hex}")
    db.commit()
    return db


def get_meta(db: sqlite3.Connection, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO metadata(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def append_event(
    db: sqlite3.Connection,
    turn_id: str,
    event_type: str,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> int:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(encoded) > MAX_EVENT_TEXT:
        encoded = json.dumps(
            {
                "truncated": True,
                "preview": encoded[:MAX_EVENT_TEXT],
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    identifier = event_id or f"event-{uuid4().hex}"
    cursor = db.execute(
        "INSERT OR IGNORE INTO events(id, turn_id, type, payload, at) VALUES(?, ?, ?, ?, ?)",
        (identifier, turn_id, event_type, encoded, now()),
    )
    if cursor.rowcount:
        return int(cursor.lastrowid)
    row = db.execute("SELECT seq FROM events WHERE id=?", (identifier,)).fetchone()
    return int(row["seq"])


def turn_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def turn_with_revision(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    turn = turn_dict(row)
    revision = db.execute(
        "SELECT COALESCE(MAX(seq), 0) AS revision FROM events WHERE turn_id=?",
        (turn["id"],),
    ).fetchone()
    turn["revision"] = int(revision["revision"])
    return turn


def event_dict(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    try:
        value["payload"] = json.loads(value["payload"])
    except json.JSONDecodeError:
        value["payload"] = {"text": value["payload"]}
    return value


def init_runtime(session_id: str, started: bool) -> dict[str, Any]:
    with connect() as db:
        set_meta(db, "session_id", session_id)
        if started:
            set_meta(db, "session_started", "1")
        elif not get_meta(db, "session_started"):
            set_meta(db, "session_started", "0")
        set_meta(db, "runner_version", "2")
        runtime_id = get_meta(db, "runtime_id")
    return {
        "initialized": True,
        "session_id": session_id,
        "runtime_id": runtime_id,
        "started": started,
    }


def enqueue_turn(
    *,
    prompt: str,
    display_prompt: str,
    client_id: str,
    turn_id: str,
    mode: str,
    sender_kind: str,
    sender_sandbox: str | None,
    sender_label: str | None,
    retry_existing: bool = False,
) -> dict[str, Any]:
    if mode not in {"queue", "interrupt"}:
        raise ValueError("mode must be queue or interrupt")
    if not prompt.strip() or len(prompt) > 16_000:
        raise ValueError("model prompt must contain 1-16,000 characters")
    with connect() as db:
        existing = db.execute("SELECT * FROM turns WHERE client_id=?", (client_id,)).fetchone()
        if existing:
            if retry_existing and existing["status"] == "failed":
                db.execute(
                    "UPDATE turns SET status='queued', started_at=NULL, "
                    "finished_at=NULL, error=NULL "
                    "WHERE id=?",
                    (existing["id"],),
                )
                append_event(
                    db,
                    existing["id"],
                    "turn_status",
                    {"status": "queued", "mode": existing["mode"], "retry": True},
                )
                existing = db.execute(
                    "SELECT * FROM turns WHERE id=?", (existing["id"],)
                ).fetchone()
            return turn_with_revision(db, existing)
        created_at = now()
        db.execute(
            "INSERT INTO turns(id, client_id, prompt, display_prompt, mode, sender_kind, "
            "sender_sandbox, sender_label, status, priority, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
            (
                turn_id,
                client_id,
                prompt,
                display_prompt,
                mode,
                sender_kind,
                sender_sandbox,
                sender_label,
                0 if mode == "interrupt" else 10,
                created_at,
            ),
        )
        append_event(
            db,
            turn_id,
            "turn_status",
            {"status": "queued", "mode": mode},
        )
        if mode == "interrupt":
            set_meta(db, "interrupt_requested", turn_id)
        row = db.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
        return turn_with_revision(db, row)


def runtime_snapshot(after: int = 0) -> dict[str, Any]:
    with connect() as db:
        events = [
            event_dict(row)
            for row in db.execute("SELECT * FROM events WHERE seq>? ORDER BY seq", (after,))
        ]
        if after <= 0:
            turn_rows = db.execute("SELECT * FROM turns ORDER BY created_at, id").fetchall()
        else:
            turn_ids = {event["turn_id"] for event in events}
            turn_ids.update(
                row["id"]
                for row in db.execute(
                    "SELECT id FROM turns WHERE status IN ('queued','running','interrupting')"
                )
            )
            if turn_ids:
                placeholders = ",".join("?" for _ in turn_ids)
                turn_rows = db.execute(
                    f"SELECT * FROM turns WHERE id IN ({placeholders}) "  # noqa: S608
                    "ORDER BY created_at, id",
                    tuple(turn_ids),
                ).fetchall()
            else:
                turn_rows = []
        turns = []
        for row in turn_rows:
            turns.append(turn_with_revision(db, row))
        cursor_row = db.execute("SELECT COALESCE(MAX(seq), 0) AS cursor FROM events").fetchone()
        active = db.execute(
            "SELECT * FROM turns WHERE status IN ('running','interrupting') "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        queued_row = db.execute(
            "SELECT COUNT(*) AS count FROM turns WHERE status='queued'"
        ).fetchone()
        return {
            "runtime_id": get_meta(db, "runtime_id"),
            "session_id": get_meta(db, "session_id"),
            "cursor": int(cursor_row["cursor"]),
            "active_turn_id": active["id"] if active else None,
            "turn_status": active["status"] if active else "idle",
            "queued": int(queued_row["count"]),
            "turns": turns,
            "events": events,
        }


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in (
            "text",
            "content",
            "output",
            "OkayOutput",
            "ErrorOutput",
            "error",
            "message",
        ):
            if key in value:
                content = _content_text(value.get(key))
                if content:
                    return content
        return json.dumps(value, indent=2, ensure_ascii=False)
    if isinstance(value, list):
        return "\n".join(filter(None, (_content_text(item) for item in value)))
    return ""


def normalize_stream_event(raw: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    if raw.get("method") not in {"session/update", "_x.ai/session/update"}:
        return None
    params = raw.get("params")
    update = params.get("update") if isinstance(params, dict) else None
    if not isinstance(update, dict):
        return None
    kind = update.get("sessionUpdate")
    if kind == "agent_message_chunk":
        return "assistant_text", {"text": _content_text(update.get("content"))}
    if kind == "agent_thought_chunk":
        return "reasoning", {"text": _content_text(update.get("content"))}
    if kind == "tool_call":
        raw_input = update.get("rawInput")
        tool_name = raw_input.get("tool_name") if isinstance(raw_input, dict) else None
        tool_input = (
            raw_input.get("tool_input", raw_input)
            if isinstance(raw_input, dict)
            else raw_input
        )
        return "tool", {
            "toolCallId": update.get("toolCallId"),
            "title": tool_name or update.get("title") or update.get("kind") or "Tool call",
            "kind": update.get("kind"),
            "status": update.get("status") or "pending",
            "input": tool_input,
        }
    if kind == "tool_call_update":
        payload = {
            "toolCallId": update.get("toolCallId"),
            "status": update.get("status") or "in_progress",
        }
        title = update.get("title") or update.get("kind")
        if title:
            payload["title"] = title
        raw_input = update.get("rawInput")
        if raw_input is not None:
            payload["input"] = (
                raw_input.get("tool_input", raw_input)
                if isinstance(raw_input, dict)
                else raw_input
            )
        content = _content_text(update.get("content") or update.get("rawOutput"))
        if content:
            payload["content"] = content
        return "tool", payload
    if kind == "turn_completed":
        return "turn_completed", {
            "stopReason": update.get("stop_reason"),
            "usage": update.get("usage"),
        }
    return None


def stream_event_id(turn_id: str, raw: dict[str, Any]) -> str:
    raw_id = raw.get("_meta", {}).get("eventId")
    if isinstance(raw_id, str) and raw_id:
        return f"{turn_id}:{raw_id}"
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"{turn_id}:derived:{digest}"


def grok_command(db: sqlite3.Connection, prompt: str) -> list[str]:
    session_id = get_meta(db, "session_id")
    if not session_id:
        raise RuntimeError("runner has not been initialized with a session id")
    command = [
        "grok",
        "--always-approve",
        "--output-format",
        "streaming-json",
    ]
    model = os.environ.get("GTZ_GROK_MODEL")
    effort = os.environ.get("GTZ_REASONING_EFFORT")
    if model:
        command.extend(["--model", model])
    if effort:
        command.extend(["--reasoning-effort", effort])
    if get_meta(db, "session_started") == "1":
        command.extend(["--resume", session_id])
    else:
        command.extend(["--session-id", session_id])
    command.extend(["-p", prompt])
    return command


async def pump_output(proc: asyncio.subprocess.Process, turn_id: str) -> dict[str, bool]:
    result = {"completed": False, "saw_session": False}
    if proc.stdout is None:
        raise RuntimeError("Grok process stdout was not captured")
    while line := await proc.stdout.readline():
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            with connect() as db:
                append_event(db, turn_id, "diagnostic", {"text": text})
            continue
        params = raw.get("params")
        if isinstance(params, dict) and isinstance(params.get("sessionId"), str):
            result["saw_session"] = True
        normalized = normalize_stream_event(raw)
        if normalized:
            event_type, payload = normalized
            with connect() as db:
                append_event(
                    db,
                    turn_id,
                    event_type,
                    payload,
                    event_id=stream_event_id(turn_id, raw),
                )
            if event_type == "turn_completed":
                result["completed"] = True
    return result


def updates_path(session_id: str) -> Path:
    grok_home = Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok")))
    return grok_home / "sessions" / "%2Fworkspace%2Fproject" / session_id / "updates.jsonl"


def consume_update_lines(path: Path, offset: int, turn_id: str) -> tuple[int, dict[str, bool]]:
    result = {"completed": False, "saw_session": False}
    if not path.exists():
        return offset, result
    size = path.stat().st_size
    if size < offset:
        offset = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        for line in handle:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            params = raw.get("params")
            if isinstance(params, dict) and isinstance(params.get("sessionId"), str):
                result["saw_session"] = True
            normalized = normalize_stream_event(raw)
            if not normalized:
                continue
            event_type, payload = normalized
            with connect() as db:
                append_event(
                    db,
                    turn_id,
                    event_type,
                    payload,
                    event_id=stream_event_id(turn_id, raw),
                )
            if event_type == "turn_completed":
                result["completed"] = True
        return handle.tell(), result


async def pump_updates_file(
    path: Path,
    offset: int,
    turn_id: str,
    stop: asyncio.Event,
) -> dict[str, bool]:
    result = {"completed": False, "saw_session": False}
    while not stop.is_set():
        offset, fresh = consume_update_lines(path, offset, turn_id)
        result = {key: result[key] or fresh[key] for key in result}
        await asyncio.sleep(0.1)
    offset, fresh = consume_update_lines(path, offset, turn_id)
    return {key: result[key] or fresh[key] for key in result}


async def terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()


async def run_turn(turn: sqlite3.Row) -> None:
    turn_id = str(turn["id"])
    with connect() as db:
        command = grok_command(db, str(turn["prompt"]))
        started_at = now()
        db.execute(
            "UPDATE turns SET status='running', started_at=?, error=NULL WHERE id=?",
            (started_at, turn_id),
        )
        append_event(db, turn_id, "turn_status", {"status": "running"})
        set_meta(db, "active_turn_id", turn_id)
        if get_meta(db, "interrupt_requested") == turn_id:
            set_meta(db, "interrupt_requested", "")

    session_id = ""
    with connect() as db:
        session_id = get_meta(db, "session_id")
    path = updates_path(session_id)
    update_offset = path.stat().st_size if path.exists() else 0

    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd="/workspace/project",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        with connect() as db:
            message = f"Could not start Grok: {error}"
            db.execute(
                "UPDATE turns SET status='failed', finished_at=?, error=? WHERE id=?",
                (now(), message, turn_id),
            )
            append_event(db, turn_id, "turn_status", {"status": "failed", "error": message})
            set_meta(db, "active_turn_id", "")
        return
    output_task = asyncio.create_task(pump_output(proc, turn_id))
    update_stop = asyncio.Event()
    updates_task = asyncio.create_task(pump_updates_file(path, update_offset, turn_id, update_stop))
    interrupted = False
    while proc.returncode is None:
        await asyncio.sleep(0.2)
        with connect() as db:
            requested = get_meta(db, "interrupt_requested")
            if requested and requested != turn_id:
                interrupted = True
                db.execute("UPDATE turns SET status='interrupting' WHERE id=?", (turn_id,))
                append_event(db, turn_id, "turn_status", {"status": "interrupting"})
                set_meta(db, "interrupt_requested", "")
                break
    if interrupted:
        await terminate_process(proc)
    else:
        await proc.wait()
    output_result = await output_task
    await asyncio.sleep(0.2)
    update_stop.set()
    updates_result = await updates_task

    with connect() as db:
        if output_result["saw_session"] or updates_result["saw_session"] or proc.returncode == 0:
            set_meta(db, "session_started", "1")
        if interrupted:
            status = "interrupted"
            error = "Interrupted by a newer steering message"
        elif proc.returncode == 0 or output_result["completed"] or updates_result["completed"]:
            status = "completed"
            error = None
        else:
            status = "failed"
            error = f"Grok exited with status {proc.returncode}"
        db.execute(
            "UPDATE turns SET status=?, finished_at=?, error=? WHERE id=?",
            (status, now(), error, turn_id),
        )
        append_event(db, turn_id, "turn_status", {"status": status, "error": error})
        set_meta(db, "active_turn_id", "")


def recover_stale_turns() -> int:
    with connect() as db:
        stale = db.execute(
            "SELECT id FROM turns WHERE status IN ('running','interrupting')"
        ).fetchall()
        for row in stale:
            db.execute(
                "UPDATE turns SET status='failed', finished_at=?, error=? WHERE id=?",
                (now(), "Runner restarted during the turn", row["id"]),
            )
            append_event(
                db,
                row["id"],
                "turn_status",
                {"status": "failed", "error": "Runner restarted during the turn"},
            )
        set_meta(db, "runner_started_at", now())
        return len(stale)


async def daemon() -> None:
    recover_stale_turns()
    while True:
        with connect() as db:
            turn = db.execute(
                "SELECT * FROM turns WHERE status='queued' "
                "ORDER BY priority, created_at, id LIMIT 1"
            ).fetchone()
        if turn:
            try:
                await run_turn(turn)
            except Exception as error:  # noqa: BLE001 — persist a terminal state, keep daemon alive
                with connect() as db:
                    message = f"Runner error: {error}"
                    db.execute(
                        "UPDATE turns SET status='failed', finished_at=?, error=? WHERE id=?",
                        (now(), message, turn["id"]),
                    )
                    append_event(
                        db,
                        turn["id"],
                        "turn_status",
                        {"status": "failed", "error": message},
                    )
                    set_meta(db, "active_turn_id", "")
        else:
            await asyncio.sleep(0.25)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--session-id", required=True)
    init.add_argument("--started", action="store_true")

    enqueue = sub.add_parser("enqueue")
    prompt = enqueue.add_mutually_exclusive_group(required=True)
    prompt.add_argument("--message")
    prompt.add_argument("--message-file")
    display = enqueue.add_mutually_exclusive_group()
    display.add_argument("--display-message")
    display.add_argument("--display-message-file")
    enqueue.add_argument("--client-id", required=True)
    enqueue.add_argument("--turn-id", required=True)
    enqueue.add_argument("--mode", choices=("queue", "interrupt"), default="queue")
    enqueue.add_argument("--sender-kind", default="operator")
    enqueue.add_argument("--sender-sandbox")
    enqueue.add_argument("--sender-label")
    enqueue.add_argument("--retry-existing", action="store_true")

    export = sub.add_parser("export")
    export.add_argument("--after", type=int, default=0)
    sub.add_parser("status")
    sub.add_parser("daemon")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "init":
        result = init_runtime(args.session_id, args.started)
    elif args.command == "enqueue":
        prompt = args.message
        if args.message_file:
            prompt = Path(args.message_file).read_text()
        display_prompt = args.display_message
        if args.display_message_file:
            display_prompt = Path(args.display_message_file).read_text()
        result = enqueue_turn(
            prompt=prompt.strip(),
            display_prompt=(display_prompt or prompt).strip(),
            client_id=args.client_id,
            turn_id=args.turn_id,
            mode=args.mode,
            sender_kind=args.sender_kind,
            sender_sandbox=args.sender_sandbox,
            sender_label=args.sender_label,
            retry_existing=args.retry_existing,
        )
    elif args.command in {"export", "status"}:
        result = runtime_snapshot(args.after if args.command == "export" else 0)
        if args.command == "status":
            result.pop("events", None)
            result.pop("turns", None)
    elif args.command == "daemon":
        try:
            asyncio.run(daemon())
        except KeyboardInterrupt:
            pass
        return
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
