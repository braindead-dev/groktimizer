"use client";

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
      <AgentChat
        key={`${agent.id}:${agent.sandboxName ?? "pending"}`}
        project={project}
        agent={agent}
      />
      {detailOpen ? (
        <div className="intelligence-column">
          <IntelligencePanel project={project} agent={agent} team={team} />
        </div>
      ) : null}
    </div>
  );
}
