"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  Activity,
  Atom,
  Bot,
  ChevronDown,
  ChevronRight,
  CircleGauge,
  FlaskConical,
  Hammer,
  Home,
  Network,
  Plus,
  Radio,
  Settings2,
  Workflow,
} from "lucide-react";
import { BrandMark } from "@/components/shared/brand-mark";
import { StatusDot } from "@/components/shared/status";
import type { Agent, Project, ResearchTeam, ViewSelection } from "@/lib/types";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

function isSelected(selection: ViewSelection, projectId: string, agentId?: string) {
  if (agentId) return selection.type === "agent" && selection.agentId === agentId;
  return selection.type === "project" && selection.projectId === projectId;
}

function AgentIcon({ agent }: { agent: Agent }) {
  if (agent.role === "orchestrator") return <Network size={13} />;
  if (agent.role === "team-orchestrator") return <Workflow size={13} />;
  if (agent.role === "implementor") return <Hammer size={13} />;
  return <FlaskConical size={13} />;
}

function AgentRow({ projectId, agent }: { projectId: string; agent: Agent }) {
  const { selection } = useResearchState();
  const dispatch = useResearchDispatch();
  const selected = isSelected(selection, projectId, agent.id);

  return (
    <button
      className={`tree-row agent-row ${selected ? "tree-row-selected" : ""}`}
      onClick={() => dispatch({ type: "select", selection: { type: "agent", projectId, agentId: agent.id } })}
      title={agent.task}
    >
      <span className="tree-icon"><AgentIcon agent={agent} /></span>
      <span className="tree-label">{agent.name}</span>
      <StatusDot status={agent.status} />
    </button>
  );
}

function TeamBranch({ projectId, team }: { projectId: string; team: ResearchTeam }) {
  const { expandedTeams, selection } = useResearchState();
  const dispatch = useResearchDispatch();
  const expanded = expandedTeams.includes(team.id);
  const selected = Boolean(team.orchestrator.sandboxName) && isSelected(selection, projectId, team.orchestrator.id);

  return (
    <div className="team-branch">
      <div className={`tree-row team-row ${selected ? "tree-row-selected" : ""}`}>
        <button
          className="tree-disclosure"
          aria-label={`${expanded ? "Collapse" : "Expand"} ${team.name}`}
          onClick={() => dispatch({ type: "toggle-team", teamId: team.id })}
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <button
          className="tree-main-action"
          disabled={!team.orchestrator.sandboxName}
          onClick={() => team.orchestrator.sandboxName && dispatch({ type: "select", selection: { type: "agent", projectId, agentId: team.orchestrator.id } })}
        >
          <span className={`team-swatch swatch-${team.accent}`} />
          <span className="tree-label">{team.name}</span>
          <StatusDot status={team.orchestrator.status} />
        </button>
      </div>
      <AnimatePresence initial={false}>
        {expanded ? (
          <motion.div
            className="team-children"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
          >
            {team.agents.filter((agent) => agent.sandboxName).map((agent) => <AgentRow key={agent.id} projectId={projectId} agent={agent} />)}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function ProjectBranch({ project }: { project: Project }) {
  const { expandedProjects, selection } = useResearchState();
  const dispatch = useResearchDispatch();
  const expanded = expandedProjects.includes(project.id);
  const selected = isSelected(selection, project.id);
  const hasLiveAgents = project.source === "live" && Boolean(
    project.orchestrator.sandboxName
      || project.implementor.sandboxName
      || project.teams.some((team) => team.orchestrator.sandboxName || team.agents.some((agent) => agent.sandboxName)),
  );

  return (
    <div className="project-branch">
      <div className={`tree-row project-row ${selected ? "tree-row-selected" : ""}`}>
        {hasLiveAgents ? (
          <button
            className="tree-disclosure"
            aria-label={`${expanded ? "Collapse" : "Expand"} ${project.name}`}
            onClick={() => dispatch({ type: "toggle-project", projectId: project.id })}
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : <span className="tree-disclosure" />}
        <button
          className="tree-main-action"
          onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}
        >
          <CircleGauge size={14} />
          <span className="tree-label project-label">{project.shortName}</span>
          <StatusDot status={project.status} />
        </button>
      </div>
      <AnimatePresence initial={false}>
        {expanded && hasLiveAgents ? (
          <motion.div
            className="project-children"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {project.orchestrator.sandboxName ? <AgentRow projectId={project.id} agent={project.orchestrator} /> : null}
            {project.teams.map((team) => <TeamBranch key={team.id} projectId={project.id} team={team} />)}
            {project.implementor.sandboxName ? <AgentRow projectId={project.id} agent={project.implementor} /> : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export function ProjectSidebar() {
  const { projects, selection, sidebarOpen, controlPlane } = useResearchState();
  const dispatch = useResearchDispatch();
  const activeCount = projects.reduce(
    (count, project) => count + [
      project.orchestrator,
      project.implementor,
      ...project.teams.flatMap((team) => [team.orchestrator, ...team.agents]),
    ].filter((agent) => agent.sandboxName && agent.status === "running").length,
    0,
  );

  return (
    <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
      <div className="sidebar-head">
        <button className="brand-button" onClick={() => dispatch({ type: "select", selection: { type: "home" } })}>
          <BrandMark />
          <span>groktimizer</span>
        </button>
        <button className="icon-button" aria-label="Workspace settings"><Settings2 size={15} /></button>
      </div>

      <nav className="primary-nav" aria-label="Primary navigation">
        <button
          className={`nav-row ${selection.type === "home" ? "nav-row-active" : ""}`}
          onClick={() => dispatch({ type: "select", selection: { type: "home" } })}
        >
          <Home size={15} /> Home
        </button>
        <button
          className={`nav-row ${selection.type === "activity" ? "nav-row-active" : ""}`}
          onClick={() => dispatch({ type: "select", selection: { type: "activity" } })}
        >
          <Activity size={15} /> Live runs <span className="nav-count">{activeCount}</span>
        </button>
        <button
          className={`nav-row ${selection.type === "new-project" ? "nav-row-active" : ""}`}
          onClick={() => dispatch({ type: "select", selection: { type: "new-project" } })}
        >
          <Plus size={15} /> New project
        </button>
      </nav>

      <div className="sidebar-section-head">
        <span>Research projects</span>
        <button className="icon-button mini" aria-label="Create project" onClick={() => dispatch({ type: "select", selection: { type: "new-project" } })}>
          <Plus size={13} />
        </button>
      </div>
      <div className="project-tree">
        {projects.map((project) => <ProjectBranch key={project.id} project={project} />)}
      </div>

      <div className="sidebar-foot">
        <div className="compute-card">
          <div className="compute-head">
            <Radio size={13} /> Compute pool
            <span>{controlPlane.mode === "live" ? `—/${controlPlane.maxConcurrentPods ?? 0}` : "—"}</span>
          </div>
          <div className="compute-meter"><span style={{ width: "0%" }} /></div>
          <div className="compute-meta">
            <span>{controlPlane.mode === "live" ? "RunPod budget" : "Not connected"}</span>
            <span>{controlPlane.mode === "live" ? "agent-managed ledger" : "no live usage"}</span>
          </div>
        </div>
        <button className="profile-row">
          <span className="profile-avatar"><Atom size={14} /></span>
          <span className="profile-copy">
            <strong>{controlPlane.mode === "live" ? "Live control plane" : "Repository baseline"}</strong>
            <small>{controlPlane.mode === "loading" ? "Connecting…" : controlPlane.mode === "live" ? `${controlPlane.project} · GitHub ${controlPlane.githubConnected ? "linked" : "read-only"}` : "No live agents"}</small>
          </span>
          <Bot size={15} />
        </button>
      </div>
    </aside>
  );
}
