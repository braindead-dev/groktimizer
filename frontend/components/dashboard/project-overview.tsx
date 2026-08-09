"use client";

import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Check, ChevronRight, Cpu, Database, Network, Sparkles, Trash2, X } from "lucide-react";
import { KpiChart } from "@/components/charts/kpi-chart";
import { StatusDot, StatusPill } from "@/components/shared/status";
import { stopResearchProject } from "@/lib/control-plane-client";
import type { Project } from "@/lib/types";
import { useResearchDispatch } from "@/store/research-store";

export function ProjectOverview({ project }: { project: Project }) {
  const dispatch = useResearchDispatch();
  const [confirmingStop, setConfirmingStop] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const lowerIsBetter = project.unit === "ms";
  const delta = project.baseline ? ((project.best - project.baseline) / project.baseline) * 100 : 0;
  const displayDelta = `${delta > 0 ? "+" : ""}${delta.toFixed(1)}%`;
  const registeredAgents = [project.orchestrator, project.implementor, ...project.teams.flatMap((team) => [team.orchestrator, ...team.agents])]
    .filter((agent) => agent.sandboxName);
  const liveAgents = registeredAgents.filter((agent) => agent.status === "running" || agent.status === "thinking");
  const supportingMetrics = [
    { label: "Lowest concurrency", value: String(project.baseline), unit: project.unit, detail: project.trend[0]?.label ?? "committed result" },
    { label: "Benchmark points", value: String(project.trend.length), unit: "", detail: "committed results" },
    project.source === "live"
      ? { label: "Registered sandboxes", value: String(registeredAgents.length), unit: "", detail: `${project.teams.length} team tracks` }
      : { label: "Source", value: "Repo", unit: "", detail: "committed benchmark" },
  ];

  async function stopProject() {
    if (project.source !== "live" || !project.projectName || stopping) return;
    setStopping(true);
    setStopError(null);
    try {
      await stopResearchProject(project.projectName);
      dispatch({ type: "select", selection: { type: "home" } });
      dispatch({ type: "refresh-control-plane" });
    } catch (error) {
      setStopError(error instanceof Error ? error.message : "The research run could not be stopped.");
      setStopping(false);
    }
  }

  return (
    <div className="project-overview page-scroll">
      <header className="project-header">
        <div>
          <div className="project-title-row"><h1>{project.shortName}</h1><StatusPill status={project.status} /></div>
          <p>{project.objective}</p>
        </div>
        <div className="project-actions">
          {project.orchestrator.sandboxName ? (
            <button
              className="primary-action"
              onClick={() => dispatch({ type: "select", selection: { type: "agent", projectId: project.id, agentId: project.orchestrator.id } })}
            >
              Open orchestrator <ArrowUpRight size={15} />
            </button>
          ) : <span className="baseline-source"><Database size={13} /> Recorded benchmark</span>}
          {project.source === "live" && project.projectName ? (
            confirmingStop ? (
              <div className="delete-confirm" role="group" aria-label="Confirm stopping research">
                <button aria-label="Cancel stopping" onClick={() => setConfirmingStop(false)} disabled={stopping}><X size={14} /></button>
                <button className="danger-action" onClick={stopProject} disabled={stopping}>
                  {stopping ? "Stopping…" : `Stop ${registeredAgents.length} sandboxes`}
                </button>
              </div>
            ) : (
              <button className="delete-project-action" onClick={() => setConfirmingStop(true)}>
                <Trash2 size={13} /> Stop research
              </button>
            )
          ) : null}
          {stopError ? <p className="delete-project-error" role="alert">{stopError}</p> : null}
        </div>
      </header>

      <section className="metric-marquee">
        <div className="metric-primary">
          <div className="metric-label"><span className="signal-pulse" /> {project.metric}</div>
          <div className="metric-value">{project.best}<span>{project.unit}</span></div>
          <div className="metric-delta delta-good">
            {lowerIsBetter ? <ArrowDownRight size={16} /> : <ArrowUpRight size={16} />}
            {displayDelta} across tested concurrency
          </div>
        </div>
        <div className="metric-secondary-grid">
          {supportingMetrics.map((metric, index) => (
            <div key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value} <small>{metric.unit}</small></strong>
              <em className={index === 0 && lowerIsBetter ? "delta-good" : undefined}>{metric.detail}</em>
            </div>
          ))}
        </div>
      </section>

      <section className="dashboard-grid">
        <div className="kpi-panel dashboard-panel">
          <div className="panel-heading"><h2>{project.metric} across measured concurrency</h2><span className="panel-meta">Committed benchmark</span></div>
          <KpiChart points={project.trend} baseline={project.baseline} unit={project.unit} lowerIsBetter={lowerIsBetter} />
        </div>

        <div className="pulse-panel dashboard-panel">
          <div className="panel-heading"><h2>{project.source === "live" ? "Research activity" : "Benchmark provenance"}</h2>{project.source === "live" ? <Network size={17} /> : <Database size={17} />}</div>
          <div className="pulse-visual">
            <div className="pulse-rings"><span /><span /><span /><i /></div>
            <div className="pulse-number"><strong>{project.source === "live" ? liveAgents.length : project.trend.length}</strong><span>{project.source === "live" ? <>agents<br />in motion</> : <>measured<br />points</>}</span></div>
          </div>
          <div className="pulse-stats">
            <div><Cpu size={13} /><span>{project.source === "live" ? "Sandboxes" : "GPU"}</span><strong>{project.source === "live" ? registeredAgents.length : "96 GB"}</strong></div>
            <div><Network size={13} /><span>Teams</span><strong>{project.teams.length}</strong></div>
          </div>
        </div>

        <div className="teams-panel dashboard-panel">
          <div className="panel-heading"><h2>Parallel tracks</h2><span className="panel-meta">{project.teams.length} teams</span></div>
          <div className="team-overview-list">
            {project.teams.length ? project.teams.map((team) => {
              const complete = team.agents.filter((agent) => agent.status === "complete").length;
              return (
                <button
                  key={team.id}
                  onClick={() => dispatch({ type: "select", selection: { type: "agent", projectId: project.id, agentId: team.orchestrator.id } })}
                >
                  <span className={`team-index swatch-${team.accent}`}>{String(project.teams.indexOf(team) + 1).padStart(2, "0")}</span>
                  <span className="team-overview-copy"><strong>{team.name}</strong><small>{team.agents.length} agents</small></span>
                  <span className="team-overview-meta"><StatusDot status={team.orchestrator.status} />{complete}/{team.agents.length} done</span>
                  <ChevronRight size={14} />
                </button>
              );
            }) : <div className="live-empty-state"><Network size={17} /><strong>No teams yet</strong><span>{project.source === "live" ? "Teams will appear here when they are created." : "This benchmark has no team activity."}</span></div>}
          </div>
        </div>

        <div className="decision-panel dashboard-panel">
          <div className="panel-heading"><h2>Benchmark evidence</h2></div>
          <div className="decision-list">
            {project.decisions.length ? project.decisions.map((decision) => (
              <div className="decision-row" key={decision.id}>
                <span className={`decision-icon decision-${decision.state}`}>
                  {decision.state === "promoted" ? <Check size={12} /> : decision.state === "validating" ? <Sparkles size={12} /> : <span>×</span>}
                </span>
                <span className="decision-copy"><strong>{decision.title}</strong><small>{decision.detail}</small></span>
                <span className="decision-impact"><strong>{decision.impact}</strong><small>{decision.time}</small></span>
              </div>
            )) : <div className="empty-decisions"><Sparkles size={18} /><span>Evidence will appear as results are validated.</span></div>}
          </div>
        </div>
      </section>
    </div>
  );
}
