export type BackendRole = "main" | "team" | "implementer" | "reconciler";

export interface LiveAgentSnapshot {
  project: string;
  team: string;
  agent: string;
  role: BackendRole;
  sandbox_name: string;
  branch: string;
  running: boolean;
  provisioning: boolean;
  log_mtime: number | null;
  turn_status: AgentTurnStatus;
  active_turn_id: string | null;
  queued: number;
  session_id: string | null;
  runtime_id: string | null;
  ingest_error: string | null;
}

export interface ResearchAgentRecord {
  id: string;
  name: string;
  role: "main" | "team" | "implementer" | "reconciler";
  status: "running" | "thinking" | "complete";
  task: string;
  branch: string;
  progress: number;
  finding: string;
  current_work: string;
  tools: string[];
}

export interface ResearchProjectRecord {
  id: string;
  title: string;
  objective: string;
  status: "running" | "complete";
  created_at: string;
  source_url: string;
  record_source_url: string;
  program_title: string;
  hardware: string;
  orchestrator: ResearchAgentRecord;
  reconciler: ResearchAgentRecord;
  teams: Array<{
    id: string;
    name: string;
    accent: "orange" | "blue" | "lime" | "violet";
    thesis: string;
    orchestrator: ResearchAgentRecord;
    agents: ResearchAgentRecord[];
  }>;
  metrics: Array<{
    key: string;
    label: string;
    unit: string;
    direction: "higher" | "lower";
    accent: "orange" | "blue" | "lime" | "violet";
    points: Array<{ label: string; value: number; elapsed_hours?: number }>;
  }>;
  decisions: Array<{
    id: string;
    title: string;
    detail: string;
    impact: string;
    state: "promoted" | "validating" | "rejected";
    time: string;
  }>;
}

export interface ControlPlaneSnapshot {
  project: string;
  project_state: {
    status: "idle" | "provisioning" | "running" | "failed" | "stopped";
    title: string;
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
    record?: ResearchProjectRecord | null;
  }>;
}

export type ControlPlaneResponse =
  | { connected: true; snapshot: ControlPlaneSnapshot }
  | { connected: false; mode: "offline"; reason: string };

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
      provisioning: boolean;
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
