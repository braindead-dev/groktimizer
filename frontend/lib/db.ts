import { existsSync } from "node:fs";
import { resolve } from "node:path";
import Database from "better-sqlite3";
import { controlPlaneRoot } from "@/lib/control-plane-server";

// Read-only view of the control plane's SQLite store. All writes go through
// gtz commands (single-writer discipline); this file may not exist until the
// first gtz command runs, so every reader degrades to empty results.

export interface StoredMessage {
  id: string;
  role: "user" | "agent";
  body: string;
  at: string;
}

export interface StoredProject {
  name: string;
  objective: string;
  status: "active" | "stopped";
  created_at: string;
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

function openDatabase(): Database.Database | null {
  const path = process.env.GTZ_DB ?? resolve(controlPlaneRoot(), ".gtz", "groktimizer.db");
  if (!existsSync(path)) return null;
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

export function readAgentHistory(sandbox: string, limit = 200): { messages: StoredMessage[]; log: string } {
  return withDatabase({ messages: [] as StoredMessage[], log: "" }, (db) => {
    const messages = (db
      .prepare(
        "SELECT id, role, body, at FROM (SELECT * FROM messages WHERE sandbox = ? ORDER BY at DESC, id DESC LIMIT ?) ORDER BY at, id",
      )
      .all(sandbox, limit) as StoredMessage[]);
    const chunks = (db
      .prepare("SELECT content FROM log_chunks WHERE sandbox = ? ORDER BY id DESC LIMIT 50")
      .all(sandbox) as Array<{ content: string }>);
    const log = chunks.reverse().map((chunk) => chunk.content).join("").slice(-16_000);
    return { messages, log };
  });
}

export function readProjectHistory(): { projects: StoredProject[]; agents: StoredAgent[] } {
  return withDatabase({ projects: [] as StoredProject[], agents: [] as StoredAgent[] }, (db) => {
    const projects = db.prepare("SELECT * FROM projects ORDER BY created_at DESC").all() as StoredProject[];
    const agents = db.prepare("SELECT * FROM agents ORDER BY created_at").all() as StoredAgent[];
    return { projects, agents };
  });
}
