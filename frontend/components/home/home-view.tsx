"use client";

import { FormEvent, KeyboardEvent, useState } from "react";
import { motion } from "motion/react";
import { ArrowRight, Gauge, Plus, Sparkles, WandSparkles } from "lucide-react";
import { BrandMark } from "@/components/shared/brand-mark";
import { StatusPill } from "@/components/shared/status";
import { sendSteeringMessage, startResearchProject } from "@/lib/control-plane-client";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

const starterPrompts = [
  "Reduce Grok 2 time-to-first-token",
  "Increase batch throughput under mixed traffic",
  "Cut KV-cache memory without quality loss",
];

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
      <header className="minimal-header">
        <div><span className="eyebrow">Autonomous model research</span></div>
        <span className="header-meta">
          {controlPlane.mode === "loading"
            ? "Connecting to control plane…"
            : controlPlane.mode === "live"
              ? `${controlPlane.maxConcurrentPods ?? 0} GPU slots budgeted`
              : "Repository baseline only"}
        </span>
      </header>

      <section className="launch-hero">
        <motion.div
          className="hero-mark"
          initial={{ opacity: 0, scale: 0.88, rotate: -8 }}
          animate={{ opacity: 1, scale: 1, rotate: 0 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        >
          <BrandMark />
        </motion.div>
        <p className="eyebrow">Groktimizer / {isCreating ? "New project" : liveOrchestrator ? "Live effort" : "New effort"}</p>
        <h1>{isCreating ? <>Start a separate<br />research project</> : liveOrchestrator ? <>What should the lab<br />do next?</> : <>What should the lab<br />make faster?</>}</h1>
        <p className="hero-subtitle">
          {creationBlocked
            ? "This hackathon control plane is pinned to one repository and one active project. Finish or archive Groktimizer before launching another; this composer will never reuse its thread."
            : liveOrchestrator
              ? "Steer the existing main orchestrator. Your message resumes its live Grok session; no additional project is created."
              : "Give the orchestrator an objective. It will build teams, run experiments, challenge results, and prepare the winning patch."}
        </p>

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
            <div className="composer-tools">
              <button type="button" className="tool-chip"><Plus size={14} /> Context</button>
              <button type="button" className="tool-chip"><Gauge size={14} /> TTFT</button>
            </div>
            <button className="launch-button" type="submit" disabled={creationBlocked || !objective.trim() || launching}>
              {creationBlocked ? "New project unavailable" : launching ? (!isCreating && liveOrchestrator ? "Sending…" : "Starting orchestrator…") : (!isCreating && liveOrchestrator ? "Steer orchestrator" : "Launch")} <ArrowRight size={15} />
            </button>
          </div>
        </form>
        {launchError ? <p className="launch-error" role="alert">{launchError}</p> : null}
        <p className={`control-plane-note control-plane-note-${controlPlane.mode}`}>
          <span />
          {controlPlane.mode === "live"
            ? `Connected to ${controlPlane.project}. GitHub writes ${controlPlane.githubConnected ? "enabled" : "need GITHUB_TOKEN"}.`
            : controlPlane.mode === "loading"
              ? "Checking the local backend and Blaxel workspace."
              : controlPlane.reason ?? "Live launches require the local control plane."}
        </p>

        <div className="starter-row" aria-label="Starter objectives">
          {starterPrompts.map((prompt) => (
            <button key={prompt} onClick={() => setObjective(prompt)} disabled={creationBlocked}>
              <WandSparkles size={13} /> {prompt}
            </button>
          ))}
        </div>
      </section>

      <section className="recent-runs">
        <div className="section-title-row">
          <div><p className="eyebrow">In the lab</p><h2>Current efforts</h2></div>
          <button onClick={() => dispatch({ type: "select", selection: { type: "activity" } })}>View all activity <ArrowRight size={14} /></button>
        </div>
        <div className="recent-grid">
          {projects.slice(0, 3).map((project, index) => {
            const delta = project.baseline ? ((project.best - project.baseline) / project.baseline) * 100 : 0;
            const favorable = project.unit === "ms" ? delta <= 0 : delta >= 0;
            const active = project.teams.reduce((total, team) => total + team.agents.filter((agent) => agent.status === "running").length, 0);
            return (
              <motion.button
                className={`recent-project recent-project-${index + 1}`}
                key={project.id}
                onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}
                whileHover={{ y: -3 }}
                transition={{ duration: 0.2 }}
              >
                <div className="recent-project-top"><StatusPill status={project.status} /><span>{project.createdAt}</span></div>
                <div>
                  <p>{project.metric}</p>
                  <strong>{project.best}<small>{project.unit}</small></strong>
                  <span className={favorable ? "delta-good" : "delta-neutral"}>{delta > 0 ? "+" : ""}{delta.toFixed(1)}%</span>
                </div>
                <footer>
                  <span>{project.shortName}</span>
                  <span>{project.source === "live" ? `${active} agents live` : "committed results"}</span>
                </footer>
              </motion.button>
            );
          })}
          <button className="recent-project new-project-tile" onClick={() => dispatch({ type: "select", selection: { type: "new-project" } })}>
            <span><Sparkles size={18} /></span>
            <strong>Start another effort</strong>
            <small>Open a new optimization frontier</small>
          </button>
        </div>
      </section>
    </div>
  );
}
