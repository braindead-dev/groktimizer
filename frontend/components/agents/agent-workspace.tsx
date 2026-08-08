"use client";

import { AnimatePresence, motion } from "motion/react";
import { AgentChat } from "@/components/chat/agent-chat";
import { IntelligencePanel } from "@/components/intelligence/intelligence-panel";
import type { Agent, Project, ResearchTeam } from "@/lib/types";
import { useResearchState } from "@/store/research-store";

function findTeam(project: Project, agentId: string): ResearchTeam | undefined {
  return project.teams.find((team) => team.orchestrator.id === agentId || team.agents.some((agent) => agent.id === agentId));
}

export function AgentWorkspace({ project, agent }: { project: Project; agent: Agent }) {
  const { detailOpen } = useResearchState();
  const team = findTeam(project, agent.id);

  return (
    <div className={`agent-workspace ${detailOpen ? "detail-is-open" : "detail-is-closed"}`}>
      <AgentChat project={project} agent={agent} />
      <AnimatePresence initial={false}>
        {detailOpen ? (
          <motion.div
            className="intelligence-column"
            initial={{ opacity: 0, x: 18 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 18 }}
            transition={{ duration: 0.2 }}
          >
            <IntelligencePanel project={project} agent={agent} team={team} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
