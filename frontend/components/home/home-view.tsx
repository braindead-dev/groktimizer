"use client";

import { FormEvent, KeyboardEvent, useState } from "react";
import { ArrowRight, ArrowUp } from "lucide-react";
import { BrandLockup } from "@/components/shared/brand-mark";
import { StatusPill } from "@/components/shared/status";
import { sendSteeringMessage, startResearchProject } from "@/lib/control-plane-client";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

export function HomeView() {
  const { projects, controlPlane } = useResearchState();
  const dispatch = useResearchDispatch();
  const [objective, setObjective] = useState("");
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const liveProject = projects.find((project) => project.source === "live");
  const liveOrchestrator = liveProject?.orchestrator.sandboxName ? liveProject.orchestrator : null;

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = objective.trim();
    if (!trimmed || launching) return;
    setLaunchError(null);
    if (liveProject && liveOrchestrator?.sandboxName) {
      setLaunching(true);
      try {
        await sendSteeringMessage(liveOrchestrator.sandboxName, trimmed);
        setObjective("");
        dispatch({ type: "select", selection: { type: "agent", projectId: liveProject.id, agentId: liveOrchestrator.id } });
      } catch (error) {
        setLaunchError(error instanceof Error ? error.message : "The orchestrator could not be reached.");
      } finally {
        setLaunching(false);
      }
      return;
    }
    if (controlPlane.mode !== "live") {
      setLaunchError("The live control plane is not connected. Check groktimizer.toml and the local Blaxel credentials.");
      return;
    }

    setLaunching(true);
    try {
      await startResearchProject(trimmed);
      setObjective("");
      dispatch({ type: "refresh-control-plane" });
      dispatch({ type: "select", selection: { type: "project", projectId: `live-${controlPlane.project}` } });
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : "The main orchestrator could not be started.");
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
            placeholder={liveOrchestrator ? "Ask or steer the main orchestrator…" : "Describe a measurable optimization objective…"}
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
          {projects.slice(0, 3).map((project, index) => {
            const projectAgents = [
              project.orchestrator,
              project.implementor,
              ...project.teams.flatMap((team) => [team.orchestrator, ...team.agents]),
            ].filter((agent) => agent.sandboxName);
            const active = projectAgents.filter((agent) => agent.status === "running" || agent.status === "thinking").length;
            return (
              <button
                className={`recent-project recent-project-${index + 1}`}
                key={project.id}
                onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}
              >
                <div className="recent-project-top"><strong>{project.shortName}</strong><StatusPill status={project.status} /></div>
                <p className="recent-project-objective">{project.objective}</p>
                <footer>
                  {project.source === "live" ? (
                    <strong>{active} active agents</strong>
                  ) : (
                    <><strong>{project.best}<small>{project.unit}</small></strong><span>{project.metric}</span></>
                  )}
                </footer>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
