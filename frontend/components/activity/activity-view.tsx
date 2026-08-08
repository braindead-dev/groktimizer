"use client";

import { ArrowUpRight, Clock3, Cpu, Radio, Workflow } from "lucide-react";
import { StatusDot, StatusPill } from "@/components/shared/status";
import type { Agent } from "@/lib/types";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

export function ActivityView() {
  const { projects, controlPlane } = useResearchState();
  const dispatch = useResearchDispatch();
  const liveProjects = projects.filter((project) => project.source === "live");
  const agents = liveProjects.flatMap((project) => [
    ...(project.orchestrator.sandboxName ? [{ project, team: "Project", agent: project.orchestrator }] : []),
    ...project.teams.flatMap((team) => [
      ...(team.orchestrator.sandboxName ? [{ project, team: team.name, agent: team.orchestrator }] : []),
      ...team.agents.filter((agent) => agent.sandboxName).map((agent) => ({ project, team: team.name, agent })),
    ]),
    ...(project.implementor.sandboxName ? [{ project, team: "Delivery", agent: project.implementor }] : []),
  ]);
  const liveAgents = agents.filter(({ agent }) => agent.status === "running" || agent.status === "thinking");

  return (
    <div className="activity-view page-scroll">
      <header className="page-header activity-header">
        <div><p className="eyebrow">All research</p><h1>Live runs</h1><p className="page-description">One surface for every team currently thinking, testing, or synthesizing.</p></div>
        <div className="activity-summary"><Radio size={14} /><strong>{liveAgents.length}</strong> active agents</div>
      </header>

      <div className="activity-stats">
        <div><span>Active sessions</span><strong>{liveAgents.length}</strong><small>reported running</small></div>
        <div><span>Registered sandboxes</span><strong>{agents.length}</strong><small>Blaxel registry</small></div>
        <div><span>Live projects</span><strong>{liveProjects.length}</strong><small>{controlPlane.project ?? "none connected"}</small></div>
        <div><span>Streaming bridge</span><strong>{controlPlane.mode === "live" ? "SSE" : "—"}</strong><small>{controlPlane.mode === "live" ? "gtz watch" : "not connected"}</small></div>
      </div>

      <div className="run-groups">
        {liveProjects.map((project) => {
          const projectAgents = liveAgents.filter((item) => item.project.id === project.id);
          return (
            <section className="run-group" key={project.id}>
              <div className="run-group-head">
                <button onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}>
                  <Workflow size={15} /><span>{project.name}</span><ArrowUpRight size={14} />
                </button>
                <StatusPill status={project.status} />
              </div>
              <div className="agent-table" role="table" aria-label={`${project.name} active agents`}>
                {projectAgents.length ? projectAgents.map(({ agent, team }) => (
                  <AgentActivityRow
                    key={agent.id}
                    agent={agent}
                    team={team}
                    onClick={() => dispatch({ type: "select", selection: { type: "agent", projectId: project.id, agentId: agent.id } })}
                  />
                )) : <div className="live-empty-state"><Radio size={17} /><strong>No active sessions yet</strong><span>The orchestrator is registered, but no sandbox currently reports a running tmux session.</span></div>}
              </div>
            </section>
          );
        })}
        {!liveProjects.length ? (
          <div className="live-empty-state live-empty-state-page">
            <Radio size={19} />
            <strong>No live research runs</strong>
            <span>{controlPlane.mode === "loading" ? "Connecting to the control plane…" : controlPlane.reason ?? "Launch an effort from Home to create the main orchestrator."}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AgentActivityRow({ agent, team, onClick }: { agent: Agent; team: string; onClick: () => void }) {
  return (
    <button className="agent-table-row" onClick={onClick} role="row">
      <span className="agent-cell-primary"><StatusDot status={agent.status} /><span><strong>{agent.name}</strong><small>{team}</small></span></span>
      <span className="agent-task-cell">{agent.task}</span>
      <span className="progress-cell"><i><b style={{ width: `${agent.progress}%` }} /></i><em>{agent.progress}%</em></span>
      <span className="agent-meta-cell"><Cpu size={12} /> {agent.tokens}</span>
      <span className="agent-meta-cell"><Clock3 size={12} /> {agent.elapsed}</span>
      <ArrowUpRight className="row-arrow" size={14} />
    </button>
  );
}
