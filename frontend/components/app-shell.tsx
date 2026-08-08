"use client";

import { AnimatePresence, motion } from "motion/react";
import { Menu, X } from "lucide-react";
import { ActivityView } from "@/components/activity/activity-view";
import { AgentWorkspace } from "@/components/agents/agent-workspace";
import { ProjectOverview } from "@/components/dashboard/project-overview";
import { HomeView } from "@/components/home/home-view";
import { ProjectSidebar } from "@/components/sidebar/project-sidebar";
import type { Agent, Project } from "@/lib/types";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

function findAgent(project: Project, agentId: string): Agent | undefined {
  if (project.orchestrator.id === agentId) return project.orchestrator;
  if (project.implementor.id === agentId) return project.implementor;
  for (const team of project.teams) {
    if (team.orchestrator.id === agentId) return team.orchestrator;
    const agent = team.agents.find((candidate) => candidate.id === agentId);
    if (agent) return agent;
  }
}

function SelectionView() {
  const { projects, selection } = useResearchState();

  if (selection.type === "home") return <HomeView mode="home" />;
  if (selection.type === "new-project") return <HomeView mode="new-project" />;
  if (selection.type === "activity") return <ActivityView />;

  const project = projects.find((candidate) => candidate.id === selection.projectId) ?? projects[0];

  if (!project) return <HomeView mode="home" />;

  if (selection.type === "project") return <ProjectOverview project={project} />;

  const agent = findAgent(project, selection.agentId) ?? project.orchestrator;
  return <AgentWorkspace project={project} agent={agent} />;
}

export function AppShell() {
  const { selection, sidebarOpen } = useResearchState();
  const dispatch = useResearchDispatch();
  const viewKey =
    selection.type === "project" || selection.type === "agent"
      ? `${selection.type}-${selection.projectId}-${selection.type === "agent" ? selection.agentId : ""}`
      : selection.type;

  return (
    <div className="app-shell">
      <ProjectSidebar />
      <button
        className="mobile-sidebar-toggle"
        aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
        onClick={() => dispatch({ type: "toggle-sidebar" })}
      >
        {sidebarOpen ? <X size={17} /> : <Menu size={17} />}
      </button>
      {sidebarOpen ? (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => dispatch({ type: "close-sidebar" })}
        />
      ) : null}
      <main className="main-stage">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            className="view-transition"
            key={viewKey}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -3 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
          >
            <SelectionView />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
