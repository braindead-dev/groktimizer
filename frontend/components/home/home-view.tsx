"use client";

import { FormEvent, KeyboardEvent, useState } from "react";
import { ArrowRight, ArrowUp } from "lucide-react";
import { BrandLockup } from "@/components/shared/brand-mark";
import { StatusDot, StatusPill } from "@/components/shared/status";
import { startResearchProject } from "@/lib/control-plane-client";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

function projectIdFor(objective: string) {
  const stem = objective.toLowerCase().replace(/[^a-z0-9]+/g, "").slice(0, 17) || "research";
  return `${stem}${crypto.randomUUID().replaceAll("-", "").slice(0, 6)}`;
}

export function HomeView() {
  const { projects, controlPlane } = useResearchState();
  const dispatch = useResearchDispatch();
  const [objective, setObjective] = useState("");
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const liveProjects = projects.filter((project) => project.source === "live");

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = objective.trim();
    if (!trimmed || launching) return;
    setLaunchError(null);
    if (controlPlane.mode !== "live" || !controlPlane.project) {
      setLaunchError("The live control plane is not connected. Check groktimizer.toml and the local Blaxel credentials.");
      return;
    }

    const projectName = liveProjects.length === 0 ? controlPlane.project : projectIdFor(trimmed);
    setLaunching(true);
    dispatch({ type: "project-launch-requested", project: projectName, objective: trimmed });
    setObjective("");
    try {
      await startResearchProject(trimmed, projectName);
      dispatch({ type: "refresh-control-plane" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "The main orchestrator could not be started.";
      dispatch({ type: "project-launch-failed", project: projectName, error: message });
    } finally {
      setLaunching(false);
    }
  }

  return (
    <div className="home-view page-scroll">
      <section className="launch-hero">
        <div className="hero-mark">
          <BrandLockup />
        </div>
        <form className="launch-composer" onSubmit={launch}>
          <textarea
            aria-label="Research objective"
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="What would you like to optimize?"
            rows={1}
          />
          <div className="composer-toolbar">
            <button className="launch-button" type="submit" aria-label={launching ? "Sending" : "Send objective"} disabled={!objective.trim() || launching}>
              <ArrowUp size={18} />
            </button>
          </div>
        </form>
        {launchError ? <p className="launch-error" role="alert">{launchError}</p> : null}
      </section>

      <section className="recent-runs">
        <div className="section-title-row">
          <h2>Current efforts</h2>
          <button onClick={() => dispatch({ type: "select", selection: { type: "activity" } })}>View all activity <ArrowRight size={14} /></button>
        </div>
        <div className="recent-grid">
          {(liveProjects.length ? liveProjects.slice(0, 2) : projects.slice(0, 1)).map((project, index) => {
            const projectAgents = [
              project.orchestrator,
              project.implementor,
              ...project.teams.flatMap((team) => [team.orchestrator, ...team.agents]),
            ].filter((agent) => agent.sandboxName);
            return (
              <button
                className={`recent-project recent-project-${index + 1}`}
                key={project.id}
                onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}
              >
                <div className="recent-project-top">
                  <strong>{project.shortName}</strong>
                  {project.source === "live" ? (
                    <span className="recent-project-agent-count"><StatusDot status={project.status} />{projectAgents.length} agents</span>
                  ) : <StatusPill status={project.status} />}
                </div>
                <p className="recent-project-objective">{project.objective}</p>
                {project.source !== "live" ? (
                  <footer><strong>{project.best}<small> {project.unit} {project.metric.toLowerCase()}</small></strong></footer>
                ) : null}
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
