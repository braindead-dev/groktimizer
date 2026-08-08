"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowUp,
  Brain,
  ChevronDown,
  CircleGauge,
  Code2,
  Mic,
  Paperclip,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { StatusPill } from "@/components/shared/status";
import { useAgentStream } from "@/hooks/use-agent-stream";
import { sendSteeringMessage } from "@/lib/control-plane-client";
import type { Agent, Message, Project } from "@/lib/types";
import { useResearchDispatch } from "@/store/research-store";

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

function Composer({ agent }: { agent: Agent }) {
  const [draft, setDraft] = useState("");
  const [responding, setResponding] = useState(false);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = draft.trim();
    if (!body || responding) return;
    if (!agent.sandboxName) return;
    setDraft("");
    setResponding(true);
    setDeliveryError(null);
    try {
      await sendSteeringMessage(agent.sandboxName, body);
    } catch {
      setDraft(body);
      setDeliveryError("Delivery failed. The sandbox did not accept this message, so it was not added to the conversation.");
    } finally {
      setResponding(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <div className="chat-composer-shell">
      <AnimatePresence>{responding ? <motion.div className="thinking-indicator" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><span /><span /><span /> agent is updating</motion.div> : null}</AnimatePresence>
      {deliveryError ? <p className="composer-error" role="alert">{deliveryError}</p> : null}
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
            <button className="send-button" type="submit" aria-label="Send message" disabled={!agent.sandboxName || !draft.trim() || responding}><ArrowUp size={16} /></button>
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
  const streamLabel = stream.mode !== "live"
    ? stream.mode
    : stream.activity === "receiving"
      ? "receiving"
      : stream.activity;

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [agent.messages.length, stream.latestLog, stream.messages.length]);

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
        <div className="thread-date"><span>Today</span></div>
        {agent.messages.map((message) => <MessageBlock key={message.id} message={message} />)}
        {stream.messages.map((message) => (
          <MessageBlock
            key={message.id}
            message={{ id: message.id, kind: "user", body: message.body, time: new Date(message.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) }}
          />
        ))}
        {stream.latestLog ? (
          <div className="live-log-block">
            <div className="message-kicker"><Code2 size={13} /> Live session output<span>{streamLabel}</span></div>
            <pre>{stream.latestLog.split("\n").slice(-18).join("\n")}</pre>
          </div>
        ) : null}
        <div ref={threadEnd} />
      </div>
      <Composer agent={agent} />
    </section>
  );
}
