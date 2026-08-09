export type BackendRole = "main" | "team" | "implementer" | "reconciler";

export interface LiveAgentSnapshot {
  project: string;
  team: string;
  agent: string;
  role: BackendRole;
  sandbox_name: string;
  branch: string;
  running: boolean;
  log_mtime: number | null;
  turn_status: AgentTurnStatus;
  active_turn_id: string | null;
  queued: number;
  session_id: string | null;
  runtime_id: string | null;
  ingest_error: string | null;
}

export interface ControlPlaneSnapshot {
  project: string;
  project_state: {
    status: "idle" | "provisioning" | "running" | "failed" | "stopped";
    objective: string;
    error: string | null;
  };
  generated_at: string;
  caps: {
    max_teams: number;
    max_agents_per_team: number;
  };
  budget: {
    spend_ceiling_usd: number;
    max_concurrent_pods: number;
  };
  research: {
    target_gain_pct: number;
    max_accuracy_loss_pct: number;
  };
  integrations: {
    blaxel: boolean;
    runpod: boolean;
    xai: boolean;
    github: boolean;
  };
  agents: LiveAgentSnapshot[];
  projects: Array<{
    project: string;
    project_state: ControlPlaneSnapshot["project_state"];
    agents: LiveAgentSnapshot[];
  }>;
}

export interface BaselineSnapshot {
  hardware: {
    gpu: string;
    vramGb: number;
    contextTokens: number;
  };
  latency: Array<{
    promptTokens: number;
    ttftMs: number;
    decodeTps: number;
    prefillTps: number;
  }>;
  throughput: Array<{
    concurrency: number;
    aggregateDecodeTps: number;
    perStreamTps: number;
    medianTtftMs: number;
    endToEndTps: number;
  }>;
  accuracy: Array<{
    task: string;
    correct: number;
    total: number;
    accuracy: number;
    unparsed: number;
  }>;
}

export type ControlPlaneResponse =
  | { connected: true; snapshot: ControlPlaneSnapshot; baseline: BaselineSnapshot }
  | { connected: false; mode: "baseline"; reason: string; baseline: BaselineSnapshot };

export type AgentTurnStatus =
  | "idle"
  | "queued"
  | "running"
  | "interrupting"
  | "completed"
  | "interrupted"
  | "failed"
  | "stopped";

export interface ChatTurn {
  id: string;
  client_id: string;
  prompt: string;
  display_prompt: string;
  mode: "queue" | "interrupt";
  sender_kind: "operator" | "agent" | "system";
  sender_sandbox: string | null;
  sender_label: string | null;
  status: Exclude<AgentTurnStatus, "idle" | "stopped">;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  revision: number;
}

export interface ChatEvent {
  id: string;
  seq: number;
  turn_id: string;
  type: "assistant_text" | "reasoning" | "tool" | "turn_completed" | "turn_status" | "diagnostic";
  payload: Record<string, unknown>;
  at: string;
}

export interface AgentConversation {
  turns: ChatTurn[];
  events: ChatEvent[];
  cursor: number;
  runtime_id: string;
  runtime: {
    runtime_id?: string | null;
    session_id?: string | null;
    active_turn_id?: string | null;
    turn_status?: AgentTurnStatus;
    queued?: number;
    cursor?: number;
  };
}

export type AgentStreamEvent =
  | { type: "connection"; data: { mode: "live" } }
  | { type: "status"; data: {
      running: boolean;
      log_mtime: number | null;
      turn_status: AgentTurnStatus;
      active_turn_id: string | null;
      queued: number;
      cursor: number;
      session_id: string | null;
      runtime_id: string | null;
    } }
  | { type: "log"; data: { content: string } }
  | { type: "snapshot" | "delta"; data: {
      runtime_id: string;
      session_id: string | null;
      events: ChatEvent[];
      turns: ChatTurn[];
      cursor: number;
    } }
  | { type: "heartbeat"; data: { at: string } }
  | { type: "error"; data: { message: string } };
