export type AgentRole = "orchestrator" | "team-orchestrator" | "researcher" | "implementor";
export type AgentStatus = "provisioning" | "running" | "thinking" | "queued" | "complete" | "blocked";
export type ProjectStatus = "running" | "paused" | "complete";
export type ProjectLifecycle = "idle" | "provisioning" | "running" | "failed" | "stopped";

export interface Agent {
  id: string;
  name: string;
  role: AgentRole;
  status: AgentStatus;
  task: string;
  progress: number;
  tokens: string;
  elapsed: string;
  sandboxName?: string;
  branchName?: string;
  runnerKind?: "durable" | "legacy" | "unavailable";
}

export interface ResearchTeam {
  id: string;
  name: string;
  accent: "orange" | "blue" | "lime" | "violet";
  thesis: string;
  orchestrator: Agent;
  agents: Agent[];
}

export interface MetricPoint {
  run: number;
  value: number;
  label: string;
}

export interface Decision {
  id: string;
  title: string;
  detail: string;
  impact: string;
  state: "promoted" | "validating" | "rejected";
  time: string;
}

export interface Project {
  id: string;
  projectName?: string;
  source?: "baseline" | "live";
  name: string;
  shortName: string;
  objective: string;
  status: ProjectStatus;
  createdAt: string;
  metric: string;
  unit: string;
  baseline: number;
  best: number;
  trend: MetricPoint[];
  orchestrator: Agent;
  implementor: Agent;
  teams: ResearchTeam[];
  decisions: Decision[];
  lifecycle?: ProjectLifecycle;
  lifecycleError?: string | null;
}

export type ViewSelection =
  | { type: "home" }
  | { type: "activity" }
  | { type: "project"; projectId: string }
  | {
      type: "agent";
      projectId: string;
      agentId: string;
      initialMessage?: { clientId: string; body: string; mode: "queue" | "interrupt" };
    };
