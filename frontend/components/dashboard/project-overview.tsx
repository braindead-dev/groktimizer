"use client";

import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Check, ChevronRight, Cpu, Database, ExternalLink, Network, Sparkles, Trash2, X } from "lucide-react";
import { KpiChart } from "@/components/charts/kpi-chart";
import { StatusDot, StatusPill } from "@/components/shared/status";
import { deleteResearchProject } from "@/lib/control-plane-client";
import type { Project } from "@/lib/types";
import { useResearchDispatch } from "@/store/research-store";

export function ProjectOverview({ project }: { project: Project }) {
  const dispatch = useResearchDispatch();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const primaryMetric = project.metrics[0];
  const lowerIsBetter = primaryMetric?.direction === "lower";
  const delta = primaryMetric?.baseline
    ? ((primaryMetric.best - primaryMetric.baseline) / primaryMetric.baseline) * 100
    : 0;
  const improvement = lowerIsBetter ? -delta : delta;
  const displayDelta = `${improvement > 0 ? "+" : ""}${improvement.toFixed(1)}%`;
  const registeredAgents = [project.orchestrator, project.implementor, ...project.teams.flatMap((team) => [team.orchestrator, ...team.agents])]
    .filter((agent) => agent.sandboxName);
  const liveAgents = registeredAgents.filter((agent) => agent.status === "running" || agent.status === "thinking");
  const supportingMetrics = [
    ...project.metrics.slice(1, 3).map((metric) => ({
      label: metric.label,
      value: String(metric.best),
      unit: metric.unit,
      detail: metric.direction === "lower" ? "lower is better" : "higher is better",
    })),
    { label: "Active agents", value: String(liveAgents.length), unit: "", detail: `${project.teams.length} parallel teams` },
    { label: "Validated steps", value: String(primaryMetric?.points.length ?? project.trend.length), unit: "", detail: "durable run ledger" },
  ].slice(0, 3);

  async function deleteProject() {
    if (project.source !== "live" || !project.projectName || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteResearchProject(project.projectName);
      dispatch({ type: "select", selection: { type: "home" } });
      dispatch({ type: "refresh-control-plane" });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "The project could not be deleted.");
      setDeleting(false);
    }
  }

  return (
    <div className="project-overview page-scroll">
      <header className="project-header">
        <div>
          <div className="project-title-row"><h1>{project.shortName}</h1><StatusPill status={project.status} /></div>
          <p>{project.objective}</p>
          <div className="project-provenance">
            {project.hardware ? <span><Cpu size={12} />{project.hardware}</span> : null}
            {project.sourceUrl ? <a href={project.sourceUrl} target="_blank" rel="noreferrer">Research source <ExternalLink size={11} /></a> : null}
          </div>
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
            confirmingDelete ? (
              <div className="delete-confirm" role="group" aria-label="Confirm deleting project">
                <button aria-label="Cancel deletion" onClick={() => setConfirmingDelete(false)} disabled={deleting}><X size={14} /></button>
                <button className="danger-action" onClick={deleteProject} disabled={deleting}>
                  {deleting ? "Deleting…" : `Delete project and ${registeredAgents.length} sandboxes`}
                </button>
              </div>
            ) : (
              <button className="delete-project-action" onClick={() => setConfirmingDelete(true)}>
                <Trash2 size={13} /> Delete project
              </button>
            )
          ) : null}
          {deleteError ? <p className="delete-project-error" role="alert">{deleteError}</p> : null}
        </div>
      </header>

      <section className="metric-marquee">
        <div className="metric-primary">
          <div className="metric-label"><span className="signal-pulse" /> {primaryMetric?.label ?? project.metric}</div>
          <div className="metric-value">{primaryMetric?.best ?? project.best}<span>{primaryMetric?.unit ?? project.unit}</span></div>
          <div className="metric-delta delta-good">
            {lowerIsBetter ? <ArrowDownRight size={16} /> : <ArrowUpRight size={16} />}
            {displayDelta} from measured baseline
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
          <div className="panel-heading"><h2>KPI trajectory</h2><span className="panel-meta">Validated run ledger</span></div>
          <KpiChart series={project.metrics} />
        </div>

        <div className="pulse-panel dashboard-panel">
          <div className="panel-heading"><h2>{project.source === "live" ? "Research activity" : "Benchmark provenance"}</h2>{project.source === "live" ? <Network size={17} /> : <Database size={17} />}</div>
          <div className="activity-summary">
            <span>Working now</span>
            <strong>{project.source === "live" ? liveAgents.length : project.trend.length}</strong>
            <small>{project.source === "live" ? "active research agents" : "committed measurements"}</small>
          </div>
          <div className="activity-team-strip" aria-label="Team activity">
            {project.teams.map((team) => (
              <i className={`chart-accent-${team.accent}`} key={team.id} title={team.name} />
            ))}
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
              const active = team.agents.filter((agent) => agent.status === "running" || agent.status === "thinking").length;
              return (
                <button
                  key={team.id}
                  onClick={() => dispatch({ type: "select", selection: { type: "agent", projectId: project.id, agentId: team.orchestrator.id } })}
                >
                  <span className={`team-index swatch-${team.accent}`}>{String(project.teams.indexOf(team) + 1).padStart(2, "0")}</span>
                  <span className="team-overview-copy"><strong>{team.name}</strong><small>{team.agents.length} agents</small></span>
                  <span className="team-overview-meta"><StatusDot status={team.orchestrator.status} />{active}/{team.agents.length} active</span>
                  <ChevronRight size={14} />
                </button>
              );
            }) : <div className="live-empty-state"><Network size={17} /><strong>No teams yet</strong><span>{project.source === "live" ? "Teams will appear here when they are created." : "This benchmark has no team activity."}</span></div>}
          </div>
        </div>

        <div className="decision-panel dashboard-panel">
          <div className="panel-heading"><h2>Research decisions</h2><span className="panel-meta">Evidence before promotion</span></div>
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
