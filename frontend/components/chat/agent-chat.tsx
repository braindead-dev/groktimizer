"use client";

import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowUp,
  Brain,
  ChevronDown,
  CircleGauge,
  Code2,
  Mic,
  Paperclip,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { ChatSkeleton } from "@/components/shared/skeleton";
import { StatusPill } from "@/components/shared/status";
import { useAgentStream } from "@/hooks/use-agent-stream";
import { fetchAgentHistory, sendSteeringMessage } from "@/lib/control-plane-client";
import type { ChatMessage } from "@/lib/control-plane-types";
import type { Agent, Message, Project } from "@/lib/types";
import { useResearchDispatch } from "@/store/research-store";

type HistoryStatus = "loading" | "ready" | "error";

interface PendingSend {
  clientId: string;
  body: string;
  at: string;
  state: "sending" | "failed";
}

function formatTime(at: string) {
  const parsed = Date.parse(at);
  return Number.isNaN(parsed)
    ? ""
    : new Date(parsed).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function toMessage(message: ChatMessage): Message {
  return {
    id: message.id,
    kind: message.role === "agent" ? "assistant" : "user",
    body: message.body,
    time: formatTime(message.at),
  };
}

function MessageBlock({ message }: { message: Message }) {
  if (message.kind === "user") {
    return (
      <motion.div className="chat-user-message" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <p>{message.body}</p><span>{message.time}</span>
      </motion.div>
    );
  }

  if (message.kind === "event") {
    return (
      <div className="chat-event">
        <button type="button"><Code2 size={13} /><span>{message.label}</span><small>{message.body}</small><ChevronDown size={12} /></button>
      </div>
    );
  }

  if (message.kind === "reasoning") {
    return (
      <div className="chat-reasoning">
        <div className="message-kicker"><Brain size={13} /> {message.label}<span>{message.time}</span></div>
        <p>{message.body}</p>
      </div>
    );
  }

  if (message.kind === "finding") {
    return (
      <div className="chat-finding">
        <div className="message-kicker"><Sparkles size={13} /> {message.label}<span>{message.time}</span></div>
        <p>{message.body}</p>
      </div>
    );
  }

  return (
    <motion.div className="chat-assistant-message" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <p>{message.body}</p><span>{message.time}</span>
    </motion.div>
  );
}

function PendingBlock({ pending, onRetry }: { pending: PendingSend; onRetry: (pending: PendingSend) => void }) {
  return (
    <motion.div
      className={`chat-user-message chat-message-${pending.state}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: pending.state === "sending" ? 0.6 : 1, y: 0 }}
    >
      <p>{pending.body}</p>
      {pending.state === "sending" ? (
        <span>sending…</span>
      ) : (
        <span className="chat-send-failed">
          failed
          <button type="button" onClick={() => onRetry(pending)} aria-label="Retry sending">
            <RotateCcw size={11} /> retry
          </button>
        </span>
      )}
    </motion.div>
  );
}

function Composer({ agent, onSend }: { agent: Agent; onSend: (body: string) => void }) {
  const [draft, setDraft] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = draft.trim();
    if (!body || !agent.sandboxName) return;
    setDraft("");
    onSend(body);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <div className="chat-composer-shell">
      <form className="chat-composer" onSubmit={submit}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          aria-label={`Message ${agent.name}`}
          placeholder={!agent.sandboxName ? "No live sandbox is registered for this agent" : agent.role === "orchestrator" ? "Steer the research…" : "Message this agent…"}
          disabled={!agent.sandboxName}
          rows={2}
        />
        <div className="chat-composer-toolbar">
          <div>
            <button type="button" className="composer-icon" aria-label="Attach context"><Paperclip size={15} /></button>
            <span className="access-label"><ShieldCheck size={13} /> Lab access</span>
          </div>
          <div>
            <button type="button" className="model-picker">grok-4 research <ChevronDown size={12} /></button>
            <button type="button" className="composer-icon" aria-label="Voice input"><Mic size={15} /></button>
            <button className="send-button" type="submit" aria-label="Send message" disabled={!agent.sandboxName || !draft.trim()}><ArrowUp size={16} /></button>
          </div>
        </div>
      </form>
    </div>
  );
}

export function AgentChat({ project, agent }: { project: Project; agent: Agent }) {
  const dispatch = useResearchDispatch();
  const threadEnd = useRef<HTMLDivElement>(null);
  const stream = useAgentStream(agent.sandboxName);
  const [historyStatus, setHistoryStatus] = useState<HistoryStatus>("loading");
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [historyLog, setHistoryLog] = useState("");
  const [pendingSends, setPendingSends] = useState<PendingSend[]>([]);

  const loadHistory = useCallback(async () => {
    if (!agent.sandboxName) {
      setHistoryStatus("ready");
      return;
    }
    setHistoryStatus("loading");
    try {
      const payload = await fetchAgentHistory(agent.sandboxName);
      setHistory(payload.messages);
      setHistoryLog(payload.log);
      setHistoryStatus("ready");
    } catch {
      setHistoryStatus("error");
    }
  }, [agent.sandboxName]);

  useEffect(() => {
    setHistory([]);
    setHistoryLog("");
    setPendingSends([]);
    void loadHistory();
  }, [loadHistory]);

  // Durable history (SQLite) + live stream window, deduped by message id.
  const thread = useMemo(() => {
    const seen = new Set<string>();
    const merged: Message[] = [];
    for (const message of [...history, ...stream.messages]) {
      if (seen.has(message.id)) continue;
      seen.add(message.id);
      merged.push(toMessage(message));
    }
    return merged;
  }, [history, stream.messages]);

  const confirmedIds = useMemo(() => new Set(thread.map((message) => message.id)), [thread]);
  const visiblePending = pendingSends.filter((pending) => !confirmedIds.has(pending.clientId));

  const performSend = useCallback(async (pending: PendingSend) => {
    if (!agent.sandboxName) return;
    try {
      const result = await sendSteeringMessage(agent.sandboxName, pending.body);
      setPendingSends((previous) => previous.filter((entry) => entry.clientId !== pending.clientId));
      const id = result.id ?? pending.clientId;
      setHistory((previous) =>
        previous.some((message) => message.id === id)
          ? previous
          : [...previous, { id, role: "user", body: pending.body, at: pending.at }],
      );
    } catch {
      setPendingSends((previous) =>
        previous.map((entry) =>
          entry.clientId === pending.clientId ? { ...entry, state: "failed" } : entry,
        ),
      );
    }
  }, [agent.sandboxName]);

  const handleSend = useCallback((body: string) => {
    const pending: PendingSend = {
      clientId: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      body,
      at: new Date().toISOString(),
      state: "sending",
    };
    setPendingSends((previous) => [...previous, pending]);
    void performSend(pending);
  }, [performSend]);

  const handleRetry = useCallback((pending: PendingSend) => {
    setPendingSends((previous) =>
      previous.map((entry) =>
        entry.clientId === pending.clientId ? { ...entry, state: "sending" } : entry,
      ),
    );
    void performSend({ ...pending, state: "sending" });
  }, [performSend]);

  const liveLog = stream.latestLog || historyLog;
  const sending = visiblePending.some((pending) => pending.state === "sending");
  const streamLabel = stream.mode !== "live"
    ? stream.mode
    : stream.activity === "receiving"
      ? "receiving"
      : stream.activity;

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [thread.length, visiblePending.length, liveLog]);

  return (
    <section className="agent-chat-pane">
      <header className="agent-chat-header">
        <div className="agent-header-copy">
          <button aria-label="Open project overview" onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}><CircleGauge size={14} /></button>
          <div>
            <div>
              <h1>{agent.name}</h1>
              <StatusPill status={agent.status} />
              <span className={`stream-state stream-state-${streamLabel}`}><i />{streamLabel}</span>
            </div>
            <p>{project.shortName} <span>·</span> {agent.task}</p>
          </div>
        </div>
        <button className="detail-toggle" onClick={() => dispatch({ type: "toggle-detail" })}>Workspace</button>
      </header>
      <div className="chat-thread" aria-live="polite">
        {historyStatus === "loading" ? (
          <ChatSkeleton />
        ) : historyStatus === "error" ? (
          <div className="chat-history-error" role="alert">
            <p>Message history could not be loaded.</p>
            <button type="button" onClick={() => void loadHistory()}>Retry</button>
          </div>
        ) : (
          <>
            <div className="thread-date"><span>Today</span></div>
            {thread.length === 0 && visiblePending.length === 0 ? (
              <p className="chat-empty">No messages yet. Steer this agent to start the thread.</p>
            ) : null}
            {thread.map((message) => <MessageBlock key={message.id} message={message} />)}
            {visiblePending.map((pending) => (
              <PendingBlock key={pending.clientId} pending={pending} onRetry={handleRetry} />
            ))}
            {liveLog ? (
              <div className="live-log-block">
                <div className="message-kicker"><Code2 size={13} /> Live session output<span>{streamLabel}</span></div>
                <pre>{liveLog.split("\n").slice(-18).join("\n")}</pre>
              </div>
            ) : null}
          </>
        )}
        <div ref={threadEnd} />
      </div>
      <AnimatePresence>
        {sending ? (
          <motion.div className="thinking-indicator" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <span /><span /><span /> agent is updating
          </motion.div>
        ) : null}
      </AnimatePresence>
      <Composer agent={agent} onSend={handleSend} />
    </section>
  );
}
