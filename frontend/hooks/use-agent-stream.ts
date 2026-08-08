"use client";

import { useEffect, useMemo, useState } from "react";
import { subscribeToAgent } from "@/lib/control-plane-client";
import type { AgentStreamEvent, ChatMessage } from "@/lib/control-plane-types";

export type StreamMode = "connecting" | "live" | "reconnecting" | "unavailable";
export type StreamActivity = "receiving" | "idle" | "stopped" | "connecting";

function mergeMessages(previous: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  // The watcher tails a rolling window, so incoming is a suffix of the full
  // history — append what's new instead of replacing (which dropped history).
  const seen = new Set(previous.map((message) => message.id));
  const fresh = incoming.filter((message) => !seen.has(message.id));
  return fresh.length ? [...previous, ...fresh] : previous;
}

export function useAgentStream(agentId?: string) {
  const [mode, setMode] = useState<StreamMode>(agentId ? "connecting" : "unavailable");
  const [latestLog, setLatestLog] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [running, setRunning] = useState<boolean | null>(null);
  const [lastLogAt, setLastLogAt] = useState<number | null>(null);
  const [lastHeartbeatAt, setLastHeartbeatAt] = useState<number | null>(null);
  const [clock, setClock] = useState(() => Date.now());

  useEffect(() => {
    if (!agentId) return;
    return subscribeToAgent(
      agentId,
      (event: AgentStreamEvent) => {
        if (event.type === "connection") setMode(event.data.mode);
        if (event.type === "status") {
          setRunning(event.data.running);
          setLastLogAt(event.data.log_mtime ? event.data.log_mtime * 1000 : null);
        }
        if (event.type === "log") setLatestLog(event.data.content);
        if (event.type === "messages") {
          setMessages((previous) => mergeMessages(previous, event.data.messages));
        }
        if (event.type === "heartbeat") setLastHeartbeatAt(Date.parse(event.data.at));
        if (event.type === "error") setMode("reconnecting");
      },
      (connected) => {
        if (!connected) setMode("reconnecting");
      },
    );
  }, [agentId]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const activity = useMemo<StreamActivity>(() => {
    if (running === false) return "stopped";
    if (mode !== "live" || running === null) return "connecting";
    return lastLogAt !== null && clock - lastLogAt < 12_000 ? "receiving" : "idle";
  }, [clock, lastLogAt, mode, running]);

  return { mode, latestLog, messages, running, activity, lastLogAt, lastHeartbeatAt };
}
