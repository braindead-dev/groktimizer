import { existsSync } from "node:fs";
import { resolve } from "node:path";
import Database from "better-sqlite3";
import { controlPlaneRoot } from "@/lib/control-plane-server";

// Read-only view of the control plane's SQLite store. All writes go through
// gtz commands (single-writer discipline); this file may not exist until the
// first gtz command runs, so every reader degrades to empty results.

export interface StoredTurn {
  id: string;
  client_id: string;
  prompt: string;
  display_prompt: string;
  mode: "queue" | "interrupt";
  sender_kind: "operator" | "agent" | "system";
  sender_sandbox: string | null;
  sender_label: string | null;
  status: "queued" | "running" | "interrupting" | "completed" | "interrupted" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  revision: number;
}

export interface StoredTurnEvent {
  id: string;
  seq: number;
  turn_id: string;
  type: string;
  payload: Record<string, unknown>;
  at: string;
}

export interface StoredProject {
  name: string;
  objective: string;
  status: "provisioning" | "running" | "failed" | "stopped";
  error: string | null;
  created_at: string;
  updated_at: string;
  stopped_at: string | null;
}

export interface StoredAgent {
  sandbox: string;
  project: string;
  team: string;
  name: string;
  role: string;
  created_at: string;
  terminated_at: string | null;
}

export interface StoredConversation {
  turns: StoredTurn[];
  events: StoredTurnEvent[];
  cursor: number;
  runtime_id: string;
  runtime: Record<string, unknown>;
}

function openDatabase(): Database.Database | null {
  const path = process.env.GTZ_DB ?? resolve(controlPlaneRoot(), ".gtz", "groktimizer.db");
  if (!existsSync(/* turbopackIgnore: true */ path)) return null;
  return new Database(path, { readonly: true, fileMustExist: true });
}

function withDatabase<T>(fallback: T, read: (db: Database.Database) => T): T {
  let db: Database.Database | null = null;
  try {
    db = openDatabase();
    if (!db) return fallback;
    return read(db);
  } catch {
    return fallback;
  } finally {
    db?.close();
  }
}

export function readAgentHistory(sandbox: string, limit = 200): StoredConversation {
  return withDatabase({ turns: [], events: [], cursor: 0, runtime_id: "", runtime: {} }, (db) => {
    const turns = (db
      .prepare(
        "SELECT id, client_id, prompt, display_prompt, mode, sender_kind, sender_sandbox, sender_label, status, " +
        "created_at, started_at, finished_at, error, revision FROM " +
        "(SELECT * FROM turns WHERE sandbox = ? ORDER BY created_at DESC, id DESC LIMIT ?) " +
        "ORDER BY created_at, id",
      )
      .all(sandbox, limit) as StoredTurn[]);
    const ids = turns.map((turn) => turn.id);
    const rows = ids.length
      ? db.prepare(
          `SELECT id, remote_seq AS seq, turn_id, type, payload, at
           FROM turn_events
           WHERE sandbox = ? AND turn_id IN (${ids.map(() => "?").join(",")})
           ORDER BY remote_seq`,
        ).all(sandbox, ...ids) as Array<Omit<StoredTurnEvent, "payload"> & { payload: string }>
      : [];
    const events = rows.map((row) => {
      let payload: Record<string, unknown> = {};
      try {
        payload = JSON.parse(row.payload) as Record<string, unknown>;
      } catch {
        payload = { text: row.payload };
      }
      return { ...row, payload };
    });
    const agent = db.prepare(
      "SELECT runtime_id, event_cursor, runtime_json FROM agents WHERE sandbox = ?",
    ).get(sandbox) as { runtime_id: string; event_cursor: number; runtime_json: string } | undefined;
    let runtime: Record<string, unknown> = {};
    try {
      runtime = agent?.runtime_json ? JSON.parse(agent.runtime_json) as Record<string, unknown> : {};
    } catch {
      runtime = {};
    }
    return {
      turns,
      events,
      cursor: agent?.event_cursor ?? 0,
      runtime_id: agent?.runtime_id ?? "",
      runtime,
    };
  });
}

export function readProjectHistory(): { projects: StoredProject[]; agents: StoredAgent[] } {
  return withDatabase({ projects: [] as StoredProject[], agents: [] as StoredAgent[] }, (db) => {
    const projects = db.prepare("SELECT * FROM projects ORDER BY created_at DESC").all() as StoredProject[];
    const agents = db.prepare("SELECT * FROM agents ORDER BY created_at").all() as StoredAgent[];
    return { projects, agents };
  });
}
