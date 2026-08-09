"use client";

import { useState, type PointerEvent as ReactPointerEvent } from "react";
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
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import { BrandLockup, BrandMark } from "@/components/shared/brand-mark";
import { StatusDot } from "@/components/shared/status";
import { deleteResearchProject } from "@/lib/control-plane-client";
import type { Agent, Project, ResearchTeam, ViewSelection } from "@/lib/types";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

const TEAM_COLORS = [
  "#EF4444",
  "#FB923C",
  "#FBBF24",
  "#A3E635",
  "#22C55E",
  "#22D3EE",
  "#60A5FA",
  "#A78BFA",
  "#E879F9",
] as const;

function teamColor(teamId: string) {
  let hash = 0;
  for (const character of teamId) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return TEAM_COLORS[hash % TEAM_COLORS.length];
}

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
          className="team-leading-control"
          aria-label={`${expanded ? "Collapse" : "Expand"} ${team.name}`}
          onClick={() => dispatch({ type: "toggle-team", teamId: team.id })}
        >
          <span className="team-swatch team-leading-icon" style={{ backgroundColor: teamColor(team.id) }} />
          {expanded
            ? <ChevronDown className="team-leading-chevron" size={12} />
            : <ChevronRight className="team-leading-chevron" size={12} />}
        </button>
        <button
          className="tree-main-action"
          disabled={!team.orchestrator.sandboxName}
          onClick={() => team.orchestrator.sandboxName && dispatch({ type: "select", selection: { type: "agent", projectId, agentId: team.orchestrator.id } })}
        >
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
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const hasLiveAgents = project.source === "live" && Boolean(
    project.orchestrator.sandboxName
      || project.implementor.sandboxName
      || project.teams.some((team) => team.orchestrator.sandboxName || team.agents.some((agent) => agent.sandboxName)),
  );
  const agentCount = [
    project.orchestrator,
    project.implementor,
    ...project.teams.flatMap((team) => [team.orchestrator, ...team.agents]),
  ].filter((agent) => agent.sandboxName).length;

  async function deleteProject() {
    if (!project.projectName || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteResearchProject(project.projectName);
      setConfirmingDelete(false);
      dispatch({ type: "select", selection: { type: "home" } });
      dispatch({ type: "refresh-control-plane" });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "The project could not be deleted.");
      setDeleting(false);
    }
  }

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
        {project.source === "live" && project.projectName ? (
          <button
            className="project-delete-button"
            aria-label={`Delete ${project.shortName}`}
            title="Delete project"
            onClick={() => setConfirmingDelete(true)}
          >
            <Trash2 size={12} />
          </button>
        ) : null}
      </div>
      {expanded && hasLiveAgents ? (
        <div className="project-children">
          {project.orchestrator.sandboxName ? <AgentRow projectId={project.id} agent={project.orchestrator} /> : null}
          {project.teams.map((team) => <TeamBranch key={team.id} projectId={project.id} team={team} />)}
          {project.implementor.sandboxName ? <AgentRow projectId={project.id} agent={project.implementor} /> : null}
        </div>
      ) : null}
      {confirmingDelete ? (
        <div className="confirm-dialog-backdrop" role="presentation">
          <div
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={`delete-${project.id}-title`}
          >
            <header>
              <div>
                <span>Delete project</span>
                <h2 id={`delete-${project.id}-title`}>{project.shortName}</h2>
              </div>
              <button aria-label="Close confirmation" onClick={() => setConfirmingDelete(false)} disabled={deleting}>
                <X size={15} />
              </button>
            </header>
            <p>
              This removes {agentCount} {agentCount === 1 ? "sandbox" : "sandboxes"}, attributed GPU pods,
              and persisted agent activity. Git branches remain recoverable.
            </p>
            {deleteError ? <div className="confirm-dialog-error" role="alert">{deleteError}</div> : null}
            <footer>
              <button onClick={() => setConfirmingDelete(false)} disabled={deleting}>Cancel</button>
              <button className="danger-action" onClick={() => void deleteProject()} disabled={deleting}>
                <Trash2 size={12} /> {deleting ? "Deleting…" : "Delete project"}
              </button>
            </footer>
          </div>
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
          {sidebarCollapsed ? <BrandMark /> : <BrandLockup />}
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
