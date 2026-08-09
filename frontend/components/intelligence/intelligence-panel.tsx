"use client";

import { useState } from "react";
import {
  ChevronRight,
  Network,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import { StatusDot, StatusPill } from "@/components/shared/status";
import { stopAgent } from "@/lib/control-plane-client";
import type { Agent, Project, ResearchTeam } from "@/lib/types";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

function PanelShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  const dispatch = useResearchDispatch();
  return (
    <section className="intelligence-panel">
      <header className="intelligence-header">
        <div><span>{subtitle}</span><h2>{title}</h2></div>
        <div>
          <button aria-label="Close panel" onClick={() => dispatch({ type: "toggle-detail" })}><X size={15} /></button>
        </div>
      </header>
      {children}
    </section>
  );
}

function RegistryRow({ project, agent, scope }: { project: Project; agent: Agent; scope: string }) {
  const dispatch = useResearchDispatch();
  return (
    <button
      className="registry-row"
      onClick={() => dispatch({ type: "select", selection: { type: "agent", projectId: project.id, agentId: agent.id } })}
    >
      <StatusDot status={agent.status} />
      <span><strong>{agent.name}</strong><small>{scope} · {agent.sandboxName}</small></span>
      <em>{agent.elapsed}</em>
      <ChevronRight size={13} />
    </button>
  );
}

function ProjectControl({ project }: { project: Project }) {
  const dispatch = useResearchDispatch();

  function selectAgent(agent: Agent) {
    if (!agent.sandboxName) return;
    dispatch({
      type: "select",
      selection: { type: "agent", projectId: project.id, agentId: agent.id },
    });
  }

  return (
    <PanelShell title="Organization" subtitle={project.shortName}>
      <div className="org-chart-scroll">
        <button
          className="org-root-node"
          onClick={() => selectAgent(project.orchestrator)}
          disabled={!project.orchestrator.sandboxName}
        >
          <span className="org-node-icon"><Network size={16} /></span>
          <span className="org-node-copy">
            <strong>{project.orchestrator.name}</strong>
            <small>Main orchestrator</small>
          </span>
          <StatusDot status={project.orchestrator.status} />
          <ChevronRight size={13} />
        </button>

        <div className="org-trunk" />

        <div className="org-team-list">
          {project.teams.map((team) => (
            <section className={`org-team-branch org-accent-${team.accent}`} key={team.id}>
              <button
                className="org-team-node"
                onClick={() => selectAgent(team.orchestrator)}
                disabled={!team.orchestrator.sandboxName}
              >
                <span className="org-team-swatch" />
                <span className="org-node-copy">
                  <strong>{team.name}</strong>
                  <small>Team orchestrator</small>
                </span>
                <StatusDot status={team.orchestrator.status} />
                <ChevronRight size={13} />
              </button>
              <div className="org-member-list">
                {team.agents.map((agent) => (
                  <button className="org-member-node" key={agent.id} onClick={() => selectAgent(agent)}>
                    <span className="org-member-connector" />
                    <StatusDot status={agent.status} />
                    <span className="org-node-copy">
                      <strong>{agent.name}</strong>
                      <small>Implementer</small>
                    </span>
                    <ChevronRight size={12} />
                  </button>
                ))}
                {!team.agents.length ? <p>No implementers registered</p> : null}
              </div>
            </section>
          ))}
          {!project.teams.length ? (
            <div className="org-empty-state">
              <Workflow size={16} />
              <strong>No teams registered</strong>
              <span>Teams will appear here when the main orchestrator creates them.</span>
            </div>
          ) : null}
        </div>

        {project.implementor.sandboxName ? (
          <>
            <div className="org-trunk org-trunk-final" />
            <button className="org-final-node" onClick={() => selectAgent(project.implementor)}>
              <span className="org-node-icon"><Workflow size={15} /></span>
              <span className="org-node-copy">
                <strong>{project.implementor.name}</strong>
                <small>Final reconciler</small>
              </span>
              <StatusDot status={project.implementor.status} />
              <ChevronRight size={13} />
            </button>
          </>
        ) : null}
      </div>
    </PanelShell>
  );
}

function TeamControl({ project, team }: { project: Project; team: ResearchTeam }) {
  const { controlPlane } = useResearchState();
  const teamAgents = [team.orchestrator, ...team.agents].filter((agent) => agent.sandboxName);
  const active = teamAgents.filter((agent) => agent.status === "running" || agent.status === "thinking").length;

  return (
    <PanelShell title={team.name} subtitle="Team">
      <div className="team-control-scroll">
        <div className="team-summary-band">
          <div><StatusPill status={team.orchestrator.status} /><p>{team.thesis}</p></div>
          <strong>{active}<small> running</small></strong>
        </div>
        <section className="team-roster-section registry-section">
          <div className="subsection-title"><span><Workflow size={12} /> Registered team</span><small>{team.agents.length}/{controlPlane.maxAgentsPerTeam ?? "—"} implementers</small></div>
          {controlPlane.maxAgentsPerTeam !== undefined && team.agents.length >= controlPlane.maxAgentsPerTeam ? (
            <div className="capacity-notice"><strong>Implementer cap reached</strong><span>Open an implementer below and stop it before asking this team to spawn another.</span></div>
          ) : null}
          <div className="registry-list">
            {teamAgents.map((agent) => <RegistryRow key={agent.id} project={project} agent={agent} scope={agent.role} />)}
          </div>
        </section>
      </div>
    </PanelShell>
  );
}

function AgentControl({ project, agent, team }: { project: Project; agent: Agent; team?: ResearchTeam }) {
  const dispatch = useResearchDispatch();
  const [confirmingStop, setConfirmingStop] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const canStopIndividually = Boolean(agent.sandboxName)
    && agent.runnerKind !== "persistent"
    && (agent.role === "researcher" || agent.role === "implementor");

  async function handleStop() {
    if (!agent.sandboxName || stopping) return;
    setStopping(true);
    setStopError(null);
    try {
      await stopAgent(agent.sandboxName);
      dispatch({ type: "select", selection: { type: "project", projectId: project.id } });
      dispatch({ type: "refresh-control-plane" });
    } catch (error) {
      setStopError(error instanceof Error ? error.message : "The agent could not be stopped.");
      setStopping(false);
    }
  }

  return (
    <PanelShell title={agent.name} subtitle={team?.name ?? (agent.role === "implementor" ? "Reconciliation" : "Implementation")}>
      <div className="implementation-panel">
        <section className="implementation-summary">
          <StatusPill status={agent.status} />
          <p>{agent.task}</p>
        </section>
        {agent.finding ? (
          <section className="implementation-finding">
            <span>Latest finding</span>
            <p>{agent.finding}</p>
          </section>
        ) : null}
        <section className="implementation-progress" aria-label={`${agent.progress}% complete`}>
          <div><span>Research progress</span><strong>{agent.progress}%</strong></div>
          <i><span style={{ width: `${agent.progress}%` }} /></i>
          {agent.currentWork ? <p>{agent.currentWork}</p> : null}
        </section>
        <dl className="implementation-details">
          <div><dt>Branch</dt><dd>{agent.branchName ?? "Not assigned"}</dd></div>
          <div><dt>Sandbox</dt><dd>{agent.sandboxName ?? "Not registered"}</dd></div>
          <div><dt>Last activity</dt><dd>{agent.elapsed}</dd></div>
        </dl>
        {canStopIndividually ? (
          <section className="implementation-actions">
            <div><strong>Remove sandbox</strong><span>Code and commits remain on {agent.branchName ?? "the agent branch"}.</span></div>
            {confirmingStop ? (
              <div>
                <button onClick={() => setConfirmingStop(false)} disabled={stopping}>Cancel</button>
                <button className="danger-action" onClick={() => void handleStop()} disabled={stopping}>{stopping ? "Stopping…" : "Stop agent"}</button>
              </div>
            ) : (
              <button className="delete-project-action" onClick={() => setConfirmingStop(true)}><Trash2 size={12} /> Stop agent</button>
            )}
            {stopError ? <em>{stopError}</em> : null}
          </section>
        ) : null}
      </div>
    </PanelShell>
  );
}

export function IntelligencePanel({ project, agent, team }: { project: Project; agent: Agent; team?: ResearchTeam }) {
  if (agent.role === "orchestrator") return <ProjectControl project={project} />;
  if (agent.role === "team-orchestrator" && team) return <TeamControl project={project} team={team} />;
  return <AgentControl project={project} agent={agent} team={team} />;
}
