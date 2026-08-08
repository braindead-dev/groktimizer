"use client";

import type { PointerEvent as ReactPointerEvent } from "react";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  Folder,
  Hammer,
  Home,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
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
      {expanded ? (
        <div className="team-children">
          {team.agents.filter((agent) => agent.sandboxName).map((agent) => <AgentRow key={agent.id} projectId={projectId} agent={agent} />)}
        </div>
      ) : null}
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
            className="project-leading-control"
            aria-label={`${expanded ? "Collapse" : "Expand"} ${project.name}`}
            onClick={() => dispatch({ type: "toggle-project", projectId: project.id })}
          >
            <Folder className="project-leading-icon" size={14} />
            {expanded
              ? <ChevronDown className="project-leading-chevron" size={13} />
              : <ChevronRight className="project-leading-chevron" size={13} />}
          </button>
        ) : <span className="project-leading-control"><Folder size={14} /></span>}
        <button
          className="tree-main-action"
          onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}
        >
          <span className="tree-label project-label">{project.shortName}</span>
          <StatusDot status={project.status} />
        </button>
      </div>
      {expanded && hasLiveAgents ? (
        <div className="project-children">
          {project.orchestrator.sandboxName ? <AgentRow projectId={project.id} agent={project.orchestrator} /> : null}
          {project.teams.map((team) => <TeamBranch key={team.id} projectId={project.id} team={team} />)}
          {project.implementor.sandboxName ? <AgentRow projectId={project.id} agent={project.implementor} /> : null}
        </div>
      ) : null}
    </div>
  );
}

export function ProjectSidebar() {
  const { projects, selection, sidebarOpen, sidebarCollapsed, sidebarWidth } = useResearchState();
  const dispatch = useResearchDispatch();
  const activeCount = projects.reduce(
    (count, project) => count + [
      project.orchestrator,
      project.implementor,
      ...project.teams.flatMap((team) => [team.orchestrator, ...team.agents]),
    ].filter((agent) => agent.sandboxName && (agent.status === "running" || agent.status === "thinking")).length,
    0,
  );

  function beginResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (sidebarCollapsed) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    event.currentTarget.setPointerCapture(event.pointerId);
    const onMove = (moveEvent: PointerEvent) => {
      dispatch({ type: "set-sidebar-width", width: startWidth + moveEvent.clientX - startX });
    };
    const onEnd = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onEnd);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onEnd, { once: true });
  }

  return (
    <aside
      className={`sidebar ${sidebarOpen ? "sidebar-open" : ""} ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}
      style={{ "--sidebar-width": `${sidebarWidth}px` } as React.CSSProperties}
    >
      <div className="sidebar-head">
        <button className="brand-button" onClick={() => dispatch({ type: "select", selection: { type: "home" } })}>
          <BrandMark />
          <span>groktimizer</span>
        </button>
        <button
          className="sidebar-collapse-button"
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => dispatch({ type: "toggle-sidebar-collapse" })}
        >
          {sidebarCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
        </button>
      </div>

      <nav className="primary-nav" aria-label="Primary navigation">
        <button
          className={`nav-row ${selection.type === "home" ? "nav-row-active" : ""}`}
          aria-label="Home"
          title="Home"
          onClick={() => dispatch({ type: "select", selection: { type: "home" } })}
        >
          <Home size={15} /> <span className="nav-label">Home</span>
        </button>
        <button
          className={`nav-row ${selection.type === "activity" ? "nav-row-active" : ""}`}
          aria-label="Live runs"
          title="Live runs"
          onClick={() => dispatch({ type: "select", selection: { type: "activity" } })}
        >
          <Activity size={15} /> <span className="nav-label">Live runs</span> <span className="nav-count">{activeCount}</span>
        </button>
      </nav>

      <div className="sidebar-section-head">
        <span>Projects</span>
      </div>
      <div className="project-tree">
        {projects.map((project) => <ProjectBranch key={project.id} project={project} />)}
      </div>

      <button
        className="sidebar-resize-handle"
        aria-label={sidebarCollapsed ? "Expand sidebar" : "Resize sidebar"}
        title={sidebarCollapsed ? "Expand sidebar" : "Drag to resize sidebar"}
        onClick={() => sidebarCollapsed && dispatch({ type: "toggle-sidebar-collapse" })}
        onPointerDown={beginResize}
      />
    </aside>
  );
}
