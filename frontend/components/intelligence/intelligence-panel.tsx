"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  Activity,
  ChevronRight,
  CircleGauge,
  Clock3,
  Cpu,
  Network,
  Radio,
  Terminal,
  Workflow,
  X,
} from "lucide-react";
import { StatusDot, StatusPill } from "@/components/shared/status";
import type { Agent, Project, ResearchTeam } from "@/lib/types";
import { useResearchDispatch } from "@/store/research-store";

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

function registeredAgents(project: Project) {
  return [
    project.orchestrator,
    ...project.teams.flatMap((team) => [team.orchestrator, ...team.agents]),
    project.implementor,
  ].filter((agent) => agent.sandboxName);
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
  const [tab, setTab] = useState<"map" | "registry">("map");
  const agents = registeredAgents(project);
  const active = agents.filter((agent) => agent.status === "running" || agent.status === "thinking");

  return (
    <PanelShell title="Research control" subtitle="Project orchestrator">
      <div className="panel-tabs">
        <button className={tab === "map" ? "active" : ""} onClick={() => setTab("map")}><Network size={13} /> System map</button>
        <button className={tab === "registry" ? "active" : ""} onClick={() => setTab("registry")}><Activity size={13} /> Registry</button>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        {tab === "map" ? (
          <motion.div key="map" className="control-scroll" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="system-metrics">
              <div><span>Sandboxes</span><strong>{agents.length}</strong><small>Blaxel registry</small></div>
              <div><span>Running</span><strong>{active.length}</strong><small>tmux sessions</small></div>
              <div><span>Teams</span><strong>{project.teams.length}</strong><small>registered tracks</small></div>
            </div>
            <div className="topology-canvas topology-canvas-live">
              <div className="canvas-grid" />
              <button
                className="orchestrator-node orchestrator-node-button"
                onClick={() => project.orchestrator.sandboxName && dispatch({ type: "select", selection: { type: "agent", projectId: project.id, agentId: project.orchestrator.id } })}
                disabled={!project.orchestrator.sandboxName}
              >
                <span className="node-ripple" /><div><Network size={18} /></div>
                <strong>MAIN</strong><small>{project.orchestrator.sandboxName ? project.orchestrator.status : "not registered"}</small>
              </button>
              <div className="team-node-grid topology-team-list">
                {project.teams.map((team) => {
                  const running = [team.orchestrator, ...team.agents].filter((agent) => agent.status === "running" || agent.status === "thinking").length;
                  return (
                    <button
                      key={team.id}
                      className={`topology-team swatch-bg-${team.accent}`}
                      onClick={() => team.orchestrator.sandboxName && dispatch({ type: "select", selection: { type: "agent", projectId: project.id, agentId: team.orchestrator.id } })}
                      disabled={!team.orchestrator.sandboxName}
                    >
                      <span className="topology-team-index"><Workflow size={13} /></span>
                      <span><strong>{team.name}</strong><small>{team.agents.length} implementers registered</small></span>
                      <span className="topology-team-live"><StatusDot status={team.orchestrator.status} /> {running} running</span>
                      <ChevronRight size={13} />
                    </button>
                  );
                })}
                {!project.teams.length ? (
                  <div className="live-empty-state"><Workflow size={17} /><strong>No teams registered yet</strong><span>The main orchestrator creates team sandboxes through the Groktimizer MCP server.</span></div>
                ) : null}
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div key="registry" className="control-scroll registry-view" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="subsection-title"><span><Radio size={12} /> Live Blaxel registry</span><small>{agents.length} sandboxes</small></div>
            <div className="registry-list">
              {agents.map((agent) => <RegistryRow key={agent.id} project={project} agent={agent} scope={agent.role} />)}
              {!agents.length ? <div className="live-empty-state"><Radio size={17} /><strong>Registry is empty</strong><span>Launch a project to provision the main orchestrator.</span></div> : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </PanelShell>
  );
}

function TeamControl({ project, team }: { project: Project; team: ResearchTeam }) {
  const teamAgents = [team.orchestrator, ...team.agents].filter((agent) => agent.sandboxName);
  const active = teamAgents.filter((agent) => agent.status === "running" || agent.status === "thinking").length;

  return (
    <PanelShell title={team.name} subtitle="Team orchestrator">
      <div className="team-control-scroll">
        <div className="team-summary-band">
          <div><StatusPill status={team.orchestrator.status} /><p>{team.thesis}</p></div>
          <strong>{active}<small> running</small></strong>
        </div>
        <section className="team-roster-section registry-section">
          <div className="subsection-title"><span><Workflow size={12} /> Registered team</span><small>{teamAgents.length} sandboxes</small></div>
          <div className="registry-list">
            {teamAgents.map((agent) => <RegistryRow key={agent.id} project={project} agent={agent} scope={agent.role} />)}
          </div>
        </section>
      </div>
    </PanelShell>
  );
}

function AgentControl({ agent, team }: { agent: Agent; team?: ResearchTeam }) {
  return (
    <PanelShell title="Sandbox session" subtitle={team?.name ?? agent.role}>
      <div className="researcher-scroll agent-live-details">
        <div className="experiment-headline">
          <div><StatusPill status={agent.status} /><h3>{agent.name}</h3><p>{agent.task}</p></div>
          <CircleGauge size={22} />
        </div>
        <section className="agent-facts">
          <div><Terminal size={13} /><span>Sandbox</span><strong>{agent.sandboxName ?? "Not registered"}</strong></div>
          <div><Workflow size={13} /><span>Git branch</span><strong>{agent.branchName ?? "Not assigned"}</strong></div>
          <div><Radio size={13} /><span>Session</span><strong>{agent.status}</strong></div>
          <div><Clock3 size={13} /><span>Log activity</span><strong>{agent.elapsed}</strong></div>
          <div><Cpu size={13} /><span>Transport</span><strong>{agent.sandboxName ? "SSE · gtz watch" : "Unavailable"}</strong></div>
        </section>
        <div className="agent-live-note"><Radio size={15} /><p><strong>Live session output</strong>The rolling sandbox log is streamed into the chat pane. Steering messages are delivered with <code>gtz send</code>.</p></div>
      </div>
    </PanelShell>
  );
}

export function IntelligencePanel({ project, agent, team }: { project: Project; agent: Agent; team?: ResearchTeam }) {
  if (agent.role === "orchestrator") return <ProjectControl project={project} />;
  if (agent.role === "team-orchestrator" && team) return <TeamControl project={project} team={team} />;
  return <AgentControl agent={agent} team={team} />;
}
