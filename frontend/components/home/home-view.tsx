"use client";

import { FormEvent, KeyboardEvent, useState } from "react";
import { motion } from "motion/react";
import { ArrowRight, Sparkles } from "lucide-react";
import { BrandMark } from "@/components/shared/brand-mark";
import { StatusPill } from "@/components/shared/status";
import { sendSteeringMessage, startResearchProject } from "@/lib/control-plane-client";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

export function HomeView({ mode }: { mode: "home" | "new-project" }) {
  const { projects, controlPlane } = useResearchState();
  const dispatch = useResearchDispatch();
  const [objective, setObjective] = useState("");
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const liveProject = projects.find((project) => project.source === "live");
  const liveOrchestrator = liveProject?.orchestrator.sandboxName ? liveProject.orchestrator : null;
  const isCreating = mode === "new-project";
  const creationBlocked = isCreating && Boolean(liveProject);

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = objective.trim();
    if (!trimmed || launching) return;
    setLaunchError(null);
    if (!isCreating && liveProject && liveOrchestrator?.sandboxName) {
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
    if (creationBlocked) {
      setLaunchError("This control plane is pinned to one repository and already has an active project. The current orchestrator was not messaged.");
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
        <motion.div
          className="hero-mark"
          initial={{ opacity: 0, scale: 0.88, rotate: -8 }}
          animate={{ opacity: 1, scale: 1, rotate: 0 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        >
          <BrandMark />
        </motion.div>
        <h1>{isCreating ? <>Start a separate<br />research project</> : liveOrchestrator ? <>What should the lab<br />do next?</> : <>What should the lab<br />make faster?</>}</h1>
        {!liveOrchestrator || isCreating ? (
          <p className="hero-subtitle">
            {creationBlocked
              ? "This hackathon control plane is pinned to one repository and one active project. Finish or archive Groktimizer before launching another; this composer will never reuse its thread."
              : "Give the orchestrator an objective. It will build teams, run experiments, challenge results, and prepare the winning patch."}
          </p>
        ) : null}

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
            placeholder={creationBlocked ? "One active project is already attached to this repository" : !isCreating && liveOrchestrator ? "Ask or steer the main orchestrator…" : "Describe a measurable optimization objective…"}
            disabled={creationBlocked}
            rows={3}
          />
          <div className="composer-toolbar">
            <button className="launch-button" type="submit" disabled={creationBlocked || !objective.trim() || launching}>
              {creationBlocked ? "New project unavailable" : launching ? (!isCreating && liveOrchestrator ? "Sending…" : "Starting orchestrator…") : (!isCreating && liveOrchestrator ? "Steer orchestrator" : "Launch")} <ArrowRight size={15} />
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
              <motion.button
                className={`recent-project recent-project-${index + 1}`}
                key={project.id}
                onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}
                whileHover={{ y: -3 }}
                transition={{ duration: 0.2 }}
              >
                <div className="recent-project-top"><StatusPill status={project.status} /><span>{project.source === "live" ? "Live" : project.createdAt}</span></div>
                <div>
                  <p>{project.source === "live" ? "Active agents" : project.metric}</p>
                  <strong>{project.source === "live" ? active : project.best}<small>{project.source === "live" ? "" : project.unit}</small></strong>
                </div>
                <footer>
                  <span>{project.shortName}</span>
                  <span>{project.source === "live" ? `${projectAgents.length} registered` : "committed results"}</span>
                </footer>
              </motion.button>
            );
          })}
          {!liveProject ? (
            <button className="recent-project new-project-tile" onClick={() => dispatch({ type: "select", selection: { type: "new-project" } })}>
              <span><Sparkles size={18} /></span>
              <strong>Start an effort</strong>
              <small>Open a new optimization frontier</small>
            </button>
          ) : null}
        </div>
      </section>
    </div>
  );
}
