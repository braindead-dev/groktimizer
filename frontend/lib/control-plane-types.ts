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
}

export interface ControlPlaneSnapshot {
  project: string;
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

export type AgentStreamEvent =
  | { type: "connection"; data: { mode: "live" } }
  | { type: "status"; data: { running: boolean; log_mtime: number | null } }
  | { type: "log"; data: { content: string } }
  | { type: "messages"; data: { messages: Array<{ id: string; body: string; at: string }> } }
  | { type: "heartbeat"; data: { at: string } }
  | { type: "error"; data: { message: string } };
