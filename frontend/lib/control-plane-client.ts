"use client";

import type { AgentStreamEvent, ChatTurn, ControlPlaneResponse } from "@/lib/control-plane-types";

export async function fetchControlPlane(): Promise<ControlPlaneResponse> {
  const response = await fetch("/api/control-plane", { cache: "no-store" });
  if (!response.ok) throw new Error("Unable to load the control plane");
  return response.json() as Promise<ControlPlaneResponse>;
}

export async function sendSteeringMessage(
  sandbox: string,
  message: string,
  clientId: string,
  mode: "queue" | "interrupt" = "queue",
  retry = false,
) {
  const response = await fetch(`/api/agents/${encodeURIComponent(sandbox)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, clientId, mode, retry }),
  });
  const payload = await response.json().catch(() => null) as {
    sent?: boolean;
    id?: string;
    turnId?: string;
    status?: "queued" | "running";
    mode?: "queue" | "interrupt";
    turn?: ChatTurn;
    error?: string;
    code?: string;
  } | null;
  if (!response.ok || !payload?.sent || !payload.turn) {
    const error = new Error(payload?.error ?? "The steering message could not be delivered");
    Object.assign(error, { code: payload?.code });
    throw error;
  }
  return payload as {
    sent: true;
    id: string;
    turnId: string;
    status: "queued" | "running";
    mode: "queue" | "interrupt";
    turn: ChatTurn;
  };
}

export async function stopAgent(sandbox: string) {
  const response = await fetch(`/api/agents/${encodeURIComponent(sandbox)}`, { method: "DELETE" });
  const payload = await response.json().catch(() => null) as { deleted?: boolean; error?: string } | null;
  if (!response.ok || !payload?.deleted) {
    throw new Error(payload?.error ?? "The agent could not be stopped");
  }
  return payload as { deleted: true };
}

export async function interruptAgent(sandbox: string) {
  const response = await fetch(`/api/agents/${encodeURIComponent(sandbox)}/interrupt`, {
    method: "POST",
  });
  const payload = await response.json().catch(() => null) as {
    interrupted?: boolean;
    turn_id?: string | null;
    error?: string;
  } | null;
  if (!response.ok) {
    throw new Error(payload?.error ?? "The active response could not be stopped");
  }
  return {
    interrupted: payload?.interrupted === true,
    turnId: payload?.turn_id ?? null,
  };
}

export async function repairAgent(sandbox: string) {
  const response = await fetch(`/api/agents/${encodeURIComponent(sandbox)}/repair`, {
    method: "POST",
  });
  const payload = await response.json().catch(() => null) as {
    repaired?: boolean;
    session_id?: string;
    error?: string;
  } | null;
  if (!response.ok || !payload?.repaired) {
    throw new Error(payload?.error ?? "The agent runner could not be repaired");
  }
  return payload as { repaired: true; session_id: string };
}

export async function startResearchProject(objective: string, project: string) {
  const response = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objective, project }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: string } | null;
    throw new Error(payload?.error ?? "The project orchestrator could not be started");
  }
  return response.json() as Promise<{
    started: true;
    project: string;
    sandbox: string;
    state: "provisioning" | "running";
    existing?: boolean;
  }>;
}

export async function deleteResearchProject(project: string) {
  const response = await fetch(`/api/projects/${encodeURIComponent(project)}`, { method: "DELETE" });
  const payload = await response.json().catch(() => null) as {
    deleted?: boolean;
    project?: string;
    sandboxes?: number;
    error?: string;
  } | null;
  if (!response.ok || !payload?.deleted) {
    throw new Error(payload?.error ?? "The project could not be deleted");
  }
  return payload as { deleted: true; project: string; sandboxes: number };
}

export function subscribeToAgent(
  agentId: string,
  onEvent: (event: AgentStreamEvent) => void,
  onConnectionChange: (connected: boolean) => void,
) {
  const source = new EventSource(`/api/agents/${encodeURIComponent(agentId)}/stream`);
  source.onopen = () => onConnectionChange(true);
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as AgentStreamEvent);
    } catch {
      onEvent({ type: "error", data: { message: "Received an invalid stream event" } });
    }
  };
  source.onerror = () => onConnectionChange(false);
  return () => source.close();
}
