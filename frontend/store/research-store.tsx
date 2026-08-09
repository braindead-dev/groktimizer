"use client";

import { createContext, useContext, useEffect, useReducer, type Dispatch, type ReactNode } from "react";
import { fetchControlPlane } from "@/lib/control-plane-client";
import type {
  BaselineSnapshot,
  ControlPlaneSnapshot,
  LiveAgentSnapshot,
  ResearchAgentRecord,
  ResearchProjectRecord,
} from "@/lib/control-plane-types";
import type { Agent, Project, ResearchTeam, ViewSelection } from "@/lib/types";

interface ControlPlaneState {
  mode: "loading" | "baseline" | "live";
  project?: string;
  reason?: string;
  maxConcurrentPods?: number;
  maxTeams?: number;
  maxAgentsPerTeam?: number;
  githubConnected?: boolean;
}

interface ResearchState {
  projects: Project[];
  selection: ViewSelection;
  expandedProjects: string[];
  expandedTeams: string[];
  sidebarOpen: boolean;
  sidebarCollapsed: boolean;
  sidebarWidth: number;
  detailOpen: boolean;
  controlPlane: ControlPlaneState;
  controlPlaneRevision: number;
}

type Action =
  | { type: "select"; selection: ViewSelection }
  | { type: "toggle-project"; projectId: string }
  | { type: "toggle-team"; teamId: string }
  | { type: "toggle-sidebar" }
  | { type: "toggle-sidebar-collapse" }
  | { type: "set-sidebar-width"; width: number }
  | { type: "toggle-detail" }
  | { type: "close-sidebar" }
  | { type: "hydrate-control-plane"; snapshot: ControlPlaneSnapshot; baseline: BaselineSnapshot }
  | { type: "control-plane-baseline"; baseline: BaselineSnapshot; reason: string }
  | { type: "control-plane-error"; reason: string }
  | { type: "project-launch-requested"; project: string; objective: string }
  | { type: "project-launch-failed"; project: string; error: string }
  | { type: "refresh-control-plane" };

const initialState: ResearchState = {
  projects: [],
  selection: { type: "home" },
  expandedProjects: [],
  expandedTeams: [],
  sidebarOpen: false,
  sidebarCollapsed: false,
  sidebarWidth: 268,
  detailOpen: true,
  controlPlane: { mode: "loading" },
  controlPlaneRevision: 0,
};

function toggleInList(list: string[], id: string) {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}

function humanize(value: string) {
  return value.replace(/[-_]+/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function projectLabel(project: string, objective: string) {
  if (!objective.trim()) return humanize(project);
  const trimmed = objective.trim();
  if (trimmed.length <= 32) return trimmed;
  const prefix = trimmed.slice(0, 31).trimEnd();
  const lastWord = prefix.lastIndexOf(" ");
  return `${lastWord > 0 ? prefix.slice(0, lastWord) : prefix}…`;
}

function placeholderAgent(id: string, name: string, role: Agent["role"], task: string): Agent {
  return {
    id,
    name,
    role,
    status: "queued",
    task,
    progress: 0,
    tokens: "—",
    elapsed: "—",
  };
}

function projectFromBaseline(baseline: BaselineSnapshot): Project {
  const throughput = [...baseline.throughput].sort((left, right) => left.concurrency - right.concurrency);
  const first = throughput[0];
  const best = throughput.reduce((current, point) =>
    !current || point.aggregateDecodeTps > current.aggregateDecodeTps ? point : current, first);
  const mmlu = baseline.accuracy.find((result) => result.task === "mmlu");

  return {
    id: "baseline-grok2-blackwell",
    source: "baseline",
    name: "Grok-2 · Blackwell baseline",
    shortName: "Blackwell baseline",
    objective: `Committed benchmark results on ${baseline.hardware.gpu}: latency, throughput, and generative accuracy.`,
    status: "complete",
    createdAt: "Committed benchmark artifacts",
    metric: "Aggregate throughput",
    unit: "tok/s",
    baseline: Number((first?.aggregateDecodeTps ?? 0).toFixed(1)),
    best: Number((best?.aggregateDecodeTps ?? 0).toFixed(1)),
    trend: throughput.map((point) => ({
      run: point.concurrency,
      value: Number(point.aggregateDecodeTps.toFixed(1)),
      label: `Concurrency ${point.concurrency}`,
    })),
    metrics: [{
      key: "aggregate-throughput",
      label: "Aggregate throughput",
      unit: "tok/s",
      direction: "higher",
      accent: "orange",
      baseline: Number((first?.aggregateDecodeTps ?? 0).toFixed(1)),
      best: Number((best?.aggregateDecodeTps ?? 0).toFixed(1)),
      points: throughput.map((point) => ({
        run: point.concurrency,
        value: Number(point.aggregateDecodeTps.toFixed(1)),
        label: `Concurrency ${point.concurrency}`,
      })),
    }],
    orchestrator: placeholderAgent(
      "baseline-no-orchestrator",
      "No live orchestrator",
      "orchestrator",
      "Configure groktimizer.toml to connect live agents",
    ),
    implementor: placeholderAgent(
      "baseline-no-reconciler",
      "No live reconciler",
      "implementor",
      "A reconciler appears after a live research run",
    ),
    teams: [],
    decisions: [
      {
        id: "baseline-concurrency",
        title: "Eight-stream baseline",
        detail: `Aggregate decode reaches ${best?.aggregateDecodeTps.toFixed(1) ?? "—"} tok/s on the 96 GB Blackwell host.`,
        impact: `${((best?.aggregateDecodeTps ?? 0) / Math.max(first?.aggregateDecodeTps ?? 1, 1)).toFixed(2)}× TPS`,
        state: "promoted",
        time: "measured",
      },
      {
        id: "baseline-accuracy",
        title: "MMLU coherence check",
        detail: `${mmlu?.correct ?? 0}/${mmlu?.total ?? 0} generative multiple-choice answers correct with ${mmlu?.unparsed ?? 0} unparsed.`,
        impact: `${((mmlu?.accuracy ?? 0) * 100).toFixed(1)}%`,
        state: "promoted",
        time: "measured",
      },
    ],
  };
}

function recordAgent(
  source: ResearchAgentRecord,
  project: string,
  team: string,
): Agent {
  const role: Agent["role"] = source.role === "main"
    ? "orchestrator"
    : source.role === "team"
      ? "team-orchestrator"
      : source.role === "reconciler"
        ? "implementor"
        : "researcher";
  return {
    id: `gtz-${project}-${team}-${source.id}`,
    name: source.name,
    role,
    status: source.status,
    task: source.task,
    progress: source.progress,
    tokens: `${source.progress}%`,
    elapsed: source.status === "complete" ? "validated" : "live now",
    finding: source.finding,
    currentWork: source.current_work,
    sandboxName: `gtz-${project}-${team}-${source.id}`,
    branchName: source.branch,
    runnerKind: "persistent",
  };
}

function projectFromRecord(record: ResearchProjectRecord): Project {
  const metrics = record.metrics.map((metric) => {
    const values = metric.points.map((point) => point.value);
    return {
      ...metric,
      baseline: values[0] ?? 0,
      best: metric.direction === "higher" ? Math.max(...values) : Math.min(...values),
      points: metric.points.map((point, index) => ({
        run: index + 1,
        value: point.value,
        label: point.label,
      })),
    };
  });
  const primary = metrics[0];
  const teams = record.teams.map((team): ResearchTeam => ({
    id: `record-${record.id}-${team.id}`,
    name: team.name,
    accent: team.accent,
    thesis: team.thesis,
    orchestrator: recordAgent(team.orchestrator, record.id, team.id),
    agents: team.agents.map((agent) => recordAgent(agent, record.id, team.id)),
  }));
  return {
    id: `live-${record.id}`,
    projectName: record.id,
    source: "live",
    name: record.title,
    shortName: record.title,
    objective: record.objective,
    status: record.status,
    createdAt: record.created_at,
    metric: primary.label,
    unit: primary.unit,
    baseline: primary.baseline,
    best: primary.best,
    trend: primary.points,
    metrics,
    programTitle: record.program_title,
    sourceUrl: record.source_url,
    hardware: record.hardware,
    orchestrator: recordAgent(record.orchestrator, record.id, "hq"),
    implementor: recordAgent(record.reconciler, record.id, "hq"),
    teams,
    decisions: record.decisions,
    lifecycle: "running",
    lifecycleError: null,
  };
}

function elapsedFromTimestamp(timestamp: number | null, referenceTime: number) {
  if (!timestamp) return "awaiting logs";
  const seconds = Math.max(0, Math.round(referenceTime - timestamp));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3_600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3_600)}h ago`;
}

function normalizeLiveAgent(source: LiveAgentSnapshot, referenceTime: number): Agent {
  const role: Agent["role"] = source.role === "main"
    ? "orchestrator"
    : source.role === "team"
      ? "team-orchestrator"
      : source.role === "reconciler"
        ? "implementor"
        : "researcher";
  const name = source.role === "main"
    ? "Orchestrator"
    : source.role === "team"
      ? humanize(source.team)
      : source.role === "reconciler"
        ? "Final reconciler"
        : humanize(source.agent);
  const status: Agent["status"] = source.provisioning
    ? "provisioning"
    : !source.running || source.turn_status === "stopped"
      ? "blocked"
      : source.turn_status === "running" || source.turn_status === "interrupting"
        ? "thinking"
        : source.turn_status === "failed"
          ? "blocked"
          : "running";
  return {
    id: source.sandbox_name,
    name,
    role,
    status,
    task: source.provisioning
      ? `Connecting sandbox · ${source.branch}`
      : source.running
        ? `${humanize(source.turn_status)}${source.queued ? ` · ${source.queued} queued` : ""} · ${source.branch}`
        : `Sandbox session is not running · ${source.branch}`,
    progress: 0,
    tokens: "—",
    elapsed: elapsedFromTimestamp(source.log_mtime, referenceTime),
    sandboxName: source.sandbox_name,
    branchName: source.branch,
    runnerKind: source.runtime_id
      ? "durable"
      : source.ingest_error
        ? "legacy"
        : "unavailable",
  };
}

function projectFromSnapshot(snapshot: ControlPlaneSnapshot, baseline: BaselineSnapshot): Project {
  const projectRecord = snapshot.projects.find((project) => project.project === snapshot.project)?.record;
  if (projectRecord) return projectFromRecord(projectRecord);
  const base = projectFromBaseline(baseline);
  const parsedReferenceTime = Date.parse(snapshot.generated_at) / 1000;
  const referenceTime = Number.isFinite(parsedReferenceTime) ? parsedReferenceTime : 0;
  const agents = snapshot.agents.map((agent) => ({
    source: agent,
    normalized: normalizeLiveAgent(agent, referenceTime),
  }));
  const main = agents.find(({ source }) => source.role === "main")?.normalized ?? {
    ...placeholderAgent(
      `live-${snapshot.project}-orchestrator`,
      "Orchestrator",
      "orchestrator",
      snapshot.project_state.status === "failed"
        ? "Sandbox provisioning failed"
        : "Waiting for the main sandbox",
    ),
    status: snapshot.project_state.status === "failed" ? "blocked" as const : "queued" as const,
    sandboxName: snapshot.project_state.status === "idle" || snapshot.project_state.status === "stopped"
      ? undefined
      : `gtz-${snapshot.project}-hq-main`,
    branchName: "main",
  };
  const reconciler = agents.find(({ source }) => source.role === "reconciler")?.normalized ?? placeholderAgent(
    `live-${snapshot.project}-reconciler`,
    "Final reconciler",
    "implementor",
    "Dispatched after team synthesis",
  );
  const teamNames = Array.from(
    new Set(snapshot.agents.filter((agent) => agent.team !== "hq").map((agent) => agent.team)),
  ).sort();
  const accents: ResearchTeam["accent"][] = ["orange", "blue", "lime", "violet"];
  const teams = teamNames.map((teamName, index): ResearchTeam => {
    const members = agents.filter(({ source }) => source.team === teamName);
    const orchestrator = members.find(({ source }) => source.role === "team")?.normalized ?? placeholderAgent(
      `live-${snapshot.project}-${teamName}-orchestrator`,
      humanize(teamName),
      "team-orchestrator",
      "Waiting for the team sandbox",
    );
    return {
      id: `live-${snapshot.project}-${teamName}`,
      name: humanize(teamName),
      accent: accents[index % accents.length],
      thesis: "Live optimization track from the Blaxel sandbox registry.",
      orchestrator,
      agents: members
        .filter(({ source }) => source.role === "implementer")
        .map(({ normalized }) => normalized),
    };
  });
  const label = snapshot.project_state.title
    || projectLabel(snapshot.project, snapshot.project_state.objective);
  return {
    ...base,
    id: `live-${snapshot.project}`,
    projectName: snapshot.project,
    source: "live",
    name: `${label} · Live research`,
    shortName: label,
    objective: snapshot.project_state.objective || `Live hierarchical autoresearch run from the Blaxel sandbox registry. Target gain ${snapshot.research.target_gain_pct}% with at most ${snapshot.research.max_accuracy_loss_pct}% quality loss.`,
    status: snapshot.agents.some((agent) => agent.running) ? "running" : "paused",
    createdAt: "Live from Blaxel",
    orchestrator: main,
    implementor: reconciler,
    teams,
    lifecycle: snapshot.project_state.status,
    lifecycleError: snapshot.project_state.error,
  };
}

function optimisticProject(state: ResearchState, projectName: string, objective: string): Project | null {
  const base = state.projects[0];
  if (!base) return null;
  const projectId = `live-${projectName}`;
  const label = projectLabel(projectName, objective);
  return {
    ...base,
    id: projectId,
    projectName,
    source: "live",
    name: `${label} · Starting research`,
    shortName: label,
    objective,
    status: "paused",
    createdAt: "Provisioning now",
    orchestrator: {
      ...placeholderAgent(
        `live-${projectName}-orchestrator`,
        "Orchestrator",
        "orchestrator",
        "Provisioning the main sandbox",
      ),
      sandboxName: `gtz-${projectName}-hq-main`,
      branchName: "main",
    },
    teams: [],
    lifecycle: "provisioning",
    lifecycleError: null,
  };
}

function reducer(state: ResearchState, action: Action): ResearchState {
  switch (action.type) {
    case "select":
      return { ...state, selection: action.selection, sidebarOpen: false };
    case "toggle-project":
      return { ...state, expandedProjects: toggleInList(state.expandedProjects, action.projectId) };
    case "toggle-team":
      return { ...state, expandedTeams: toggleInList(state.expandedTeams, action.teamId) };
    case "toggle-sidebar":
      return { ...state, sidebarOpen: !state.sidebarOpen };
    case "toggle-sidebar-collapse":
      return { ...state, sidebarCollapsed: !state.sidebarCollapsed };
    case "set-sidebar-width":
      return { ...state, sidebarWidth: Math.min(400, Math.max(208, Math.round(action.width))) };
    case "toggle-detail":
      return { ...state, detailOpen: !state.detailOpen };
    case "close-sidebar":
      return { ...state, sidebarOpen: false };
    case "refresh-control-plane":
      return { ...state, controlPlaneRevision: state.controlPlaneRevision + 1 };
    case "project-launch-requested": {
      const project = optimisticProject(state, action.project, action.objective);
      if (!project) return state;
      return {
        ...state,
        projects: [project, ...state.projects.filter((candidate) => candidate.id !== project.id)],
        selection: {
          type: "agent",
          projectId: project.id,
          agentId: project.orchestrator.id,
        },
        expandedProjects: Array.from(new Set([project.id, ...state.expandedProjects])),
      };
    }
    case "project-launch-failed":
      return {
        ...state,
        projects: state.projects.map((project) => project.id === `live-${action.project}`
          ? {
              ...project,
              status: "paused" as const,
              lifecycle: "failed" as const,
              lifecycleError: action.error,
              orchestrator: {
                ...project.orchestrator,
                status: "blocked" as const,
                task: "Sandbox provisioning failed",
              },
            }
          : project),
      };
    case "control-plane-error":
      return { ...state, controlPlane: { mode: "baseline", reason: action.reason } };
    case "control-plane-baseline": {
      if (state.controlPlane.mode === "live") return state;
      if (state.controlPlane.mode === "baseline" && state.projects[0]?.source === "baseline") return state;
      const project = projectFromBaseline(action.baseline);
      return {
        ...state,
        projects: [project],
        selection: { type: "home" },
        expandedProjects: [],
        expandedTeams: [],
        controlPlane: { mode: "baseline", reason: action.reason },
      };
    }
    case "hydrate-control-plane": {
      const liveSnapshots = action.snapshot.projects.filter((snapshot) =>
        snapshot.agents.length > 0
        || Boolean(snapshot.record)
        || snapshot.project_state.status === "provisioning"
        || snapshot.project_state.status === "running"
        || snapshot.project_state.status === "failed");
      const hasLiveProject = liveSnapshots.length > 0;
      if (!hasLiveProject) {
        if (state.projects[0]?.lifecycle === "provisioning") return state;
        const baseline = projectFromBaseline(action.baseline);
        return {
          ...state,
          projects: [baseline],
          selection: state.selection.type === "home" || state.selection.type === "activity"
            ? state.selection
            : { type: "home" },
          expandedProjects: [],
          expandedTeams: [],
          controlPlane: {
            mode: "live",
            project: action.snapshot.project,
            maxConcurrentPods: action.snapshot.budget.max_concurrent_pods,
            maxTeams: action.snapshot.caps.max_teams,
            maxAgentsPerTeam: action.snapshot.caps.max_agents_per_team,
            githubConnected: action.snapshot.integrations.github,
          },
        };
      }
      const normalized = liveSnapshots.map((snapshot) => projectFromSnapshot(
        {
          ...action.snapshot,
          project: snapshot.project,
          project_state: snapshot.project_state,
          agents: snapshot.agents,
          projects: [{ ...snapshot }],
        },
        action.baseline,
      ));
      const pending = state.projects.filter((project) =>
        project.source === "live"
        && (project.lifecycle === "provisioning" || project.lifecycle === "failed")
        && !normalized.some((candidate) => candidate.id === project.id));
      const projects = [...pending, ...normalized];
      const selectedProjectId = state.selection.type === "project" || state.selection.type === "agent"
        ? state.selection.projectId
        : null;
      const selection = selectedProjectId && !projects.some((project) => project.id === selectedProjectId)
        ? { type: "home" as const }
        : state.selection;
      return {
        ...state,
        projects,
        selection,
        expandedProjects: Array.from(new Set([
          ...state.expandedProjects,
          ...projects.map((project) => project.id),
        ])),
        expandedTeams: state.expandedTeams.filter((teamId) =>
          projects.some((project) => project.teams.some((team) => team.id === teamId))),
        controlPlane: {
          mode: "live",
          project: action.snapshot.project,
          maxConcurrentPods: action.snapshot.budget.max_concurrent_pods,
          maxTeams: action.snapshot.caps.max_teams,
          maxAgentsPerTeam: action.snapshot.caps.max_agents_per_team,
          githubConnected: action.snapshot.integrations.github,
        },
      };
    }
    default:
      return state;
  }
}

const StateContext = createContext<ResearchState | null>(null);
const DispatchContext = createContext<Dispatch<Action> | null>(null);

export function ResearchStoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    const savedWidth = Number(window.localStorage.getItem("groktimizer-sidebar-width"));
    const savedCollapsed = window.localStorage.getItem("groktimizer-sidebar-collapsed");
    if (Number.isFinite(savedWidth)) dispatch({ type: "set-sidebar-width", width: savedWidth });
    if (savedCollapsed === "true") dispatch({ type: "toggle-sidebar-collapse" });
  }, []);

  useEffect(() => {
    window.localStorage.setItem("groktimizer-sidebar-width", String(state.sidebarWidth));
    window.localStorage.setItem("groktimizer-sidebar-collapsed", String(state.sidebarCollapsed));
  }, [state.sidebarCollapsed, state.sidebarWidth]);

  useEffect(() => {
    let active = true;
    const refresh = () => fetchControlPlane()
      .then((response) => {
        if (!active) return;
        if (response.connected) {
          dispatch({ type: "hydrate-control-plane", snapshot: response.snapshot, baseline: response.baseline });
        } else {
          dispatch({ type: "control-plane-baseline", baseline: response.baseline, reason: response.reason });
        }
      })
      .catch(() => {
        if (active) dispatch({ type: "control-plane-error", reason: "Control plane unavailable" });
      });
    void refresh();
    const interval = window.setInterval(refresh, 10_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [state.controlPlaneRevision]);

  return (
    <StateContext.Provider value={state}>
      <DispatchContext.Provider value={dispatch}>{children}</DispatchContext.Provider>
    </StateContext.Provider>
  );
}

export function useResearchState() {
  const state = useContext(StateContext);
  if (!state) throw new Error("useResearchState must be used within ResearchStoreProvider");
  return state;
}

export function useResearchDispatch() {
  const dispatch = useContext(DispatchContext);
  if (!dispatch) throw new Error("useResearchDispatch must be used within ResearchStoreProvider");
  return dispatch;
}
