"use client";

import type { AgentStreamEvent, ControlPlaneResponse } from "@/lib/control-plane-types";

export async function fetchControlPlane(): Promise<ControlPlaneResponse> {
  const response = await fetch("/api/control-plane", { cache: "no-store" });
  if (!response.ok) throw new Error("Unable to load the control plane");
  return response.json() as Promise<ControlPlaneResponse>;
}

export async function sendSteeringMessage(sandbox: string, message: string) {
  const response = await fetch(`/api/agents/${encodeURIComponent(sandbox)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) throw new Error("The steering message could not be delivered");
  return response.json() as Promise<{ sent: true }>;
}

export async function startResearchProject(objective: string) {
  const response = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ objective }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: string } | null;
    throw new Error(payload?.error ?? "The project orchestrator could not be started");
  }
  return response.json() as Promise<{ started: true; sandbox: string; state: "provisioning" }>;
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
