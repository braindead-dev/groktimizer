import type { AgentStatus, ProjectStatus } from "@/lib/types";

const statusLabels: Record<AgentStatus | ProjectStatus, string> = {
  provisioning: "Provisioning",
  running: "Running",
  thinking: "Thinking",
  queued: "Queued",
  complete: "Complete",
  blocked: "Blocked",
  paused: "Paused",
};

export function StatusDot({ status }: { status: AgentStatus | ProjectStatus }) {
  return <span className={`status-dot status-${status}`} title={statusLabels[status]} aria-label={statusLabels[status]} />;
}

export function StatusPill({ status }: { status: AgentStatus | ProjectStatus }) {
  return (
    <span className={`status-pill status-pill-${status}`}>
      <StatusDot status={status} />
      {statusLabels[status]}
    </span>
  );
}
