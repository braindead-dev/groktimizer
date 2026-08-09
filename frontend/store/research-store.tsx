"use client";

import { createContext, useContext, useEffect, useReducer, type Dispatch, type ReactNode } from "react";
import { fetchControlPlane } from "@/lib/control-plane-client";
import type { BaselineSnapshot, ControlPlaneSnapshot, LiveAgentSnapshot } from "@/lib/control-plane-types";
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
  detailOpen: boolean;
  controlPlane: ControlPlaneState;
  controlPlaneRevision: number;
}

type Action =
  | { type: "select"; selection: ViewSelection }
  | { type: "toggle-project"; projectId: string }
  | { type: "toggle-team"; teamId: string }
  | { type: "toggle-sidebar" }
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
  detailOpen: false,
  controlPlane: { mode: "loading" },
  controlPlaneRevision: 0,
};

function toggleInList(list: string[], id: string) {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}

function humanize(value: string) {
  return value.replace(/[-_]+/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
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
    ? "Project orchestrator"
    : source.role === "team"
      ? `${humanize(source.team)} orchestrator`
      : source.role === "reconciler"
        ? "Final reconciler"
      : humanize(source.agent);
  const status: Agent["status"] = !source.running || source.turn_status === "stopped"
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
    task: source.running
      ? `${humanize(source.turn_status)}${source.queued ? ` · ${source.queued} queued` : ""} · ${source.branch}`
      : `Sandbox session is not running · ${source.branch}`,
    progress: 0,
    tokens: "—",
    elapsed: elapsedFromTimestamp(source.log_mtime, referenceTime),
    sandboxName: source.sandbox_name,
    branchName: source.branch,
  };
}

function projectFromSnapshot(snapshot: ControlPlaneSnapshot, baseline: BaselineSnapshot): Project {
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
      "Project orchestrator",
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
      `${humanize(teamName)} orchestrator`,
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
  return {
    ...base,
    id: `live-${snapshot.project}`,
    projectName: snapshot.project,
    source: "live",
    name: `${humanize(snapshot.project)} · Live research`,
    shortName: humanize(snapshot.project),
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
  return {
    ...base,
    id: projectId,
    projectName,
    source: "live",
    name: `${humanize(projectName)} · Starting research`,
    shortName: humanize(projectName),
    objective,
    status: "paused",
    createdAt: "Provisioning now",
    orchestrator: {
      ...placeholderAgent(
        `live-${projectName}-orchestrator`,
        "Project orchestrator",
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
        expandedProjects: [project.id],
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
        selection: { type: "project", projectId: project.id },
        expandedProjects: [],
        expandedTeams: [],
        controlPlane: { mode: "baseline", reason: action.reason },
      };
    }
    case "hydrate-control-plane": {
      const liveSnapshots = action.snapshot.projects.filter((snapshot) =>
        snapshot.agents.length > 0
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
          selection: state.selection.type === "home" || state.selection.type === "new-project"
            ? state.selection
            : { type: "new-project" },
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
        },
        action.baseline,
      ));
      const pending = state.projects.filter((project) =>
        project.source === "live"
        && (project.lifecycle === "provisioning" || project.lifecycle === "failed")
        && !normalized.some((candidate) => candidate.id === project.id));
      const projects = [...pending, ...normalized];
      return {
        ...state,
        projects,
        selection: state.selection,
        expandedProjects: Array.from(new Set([
          ...state.expandedProjects,
          ...projects.map((project) => project.id),
        ])),
        expandedTeams: projects.flatMap((project) => project.teams.map((team) => team.id)),
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
