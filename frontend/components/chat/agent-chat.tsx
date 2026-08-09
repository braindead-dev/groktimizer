"use client";

import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Brain,
  ChevronDown,
  CircleGauge,
  Code2,
  Radio,
  RotateCcw,
  Terminal,
  Zap,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useStickToBottom } from "use-stick-to-bottom";
import { ChatSkeleton } from "@/components/shared/skeleton";
import { StatusPill } from "@/components/shared/status";
import { useAgentConversation, type PendingTurn } from "@/hooks/use-agent-conversation";
import { repairAgent } from "@/lib/control-plane-client";
import type { ChatEvent, ChatTurn } from "@/lib/control-plane-types";
import type { Agent, Project } from "@/lib/types";
import { useResearchDispatch, useResearchState } from "@/store/research-store";

interface ToolPart {
  id: string;
  title: string;
  status: string;
  content: string;
  input?: unknown;
}

interface TurnParts {
  text: string;
  reasoning: string;
  tools: ToolPart[];
}

function formatTime(at: string | null) {
  if (!at) return "";
  const parsed = Date.parse(at);
  return Number.isNaN(parsed)
    ? ""
    : new Date(parsed).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function mergeChunk(current: string, incoming: string) {
  if (!incoming) return current;
  if (!current) return incoming;
  if (incoming.startsWith(current)) return incoming;
  return `${current}${incoming}`;
}

function payloadText(event: ChatEvent) {
  return typeof event.payload.text === "string" ? event.payload.text : "";
}

function foldParts(events: ChatEvent[]): TurnParts {
  let text = "";
  let reasoning = "";
  const tools = new Map<string, ToolPart>();
  for (const event of events) {
    if (event.type === "assistant_text") text = mergeChunk(text, payloadText(event));
    if (event.type === "reasoning") reasoning = mergeChunk(reasoning, payloadText(event));
    if (event.type === "tool") {
      const id = typeof event.payload.toolCallId === "string" ? event.payload.toolCallId : event.id;
      const previous = tools.get(id);
      tools.set(id, {
        id,
        title: typeof event.payload.title === "string" ? event.payload.title : previous?.title ?? "Tool call",
        status: typeof event.payload.status === "string" ? event.payload.status : previous?.status ?? "pending",
        content: mergeChunk(
          previous?.content ?? "",
          typeof event.payload.content === "string" ? event.payload.content : "",
        ),
        input: event.payload.input ?? previous?.input,
      });
    }
  }
  return { text, reasoning, tools: [...tools.values()] };
}

function senderName(turn: ChatTurn) {
  if (turn.sender_kind === "operator") return "You";
  if (turn.sender_kind === "system") return turn.sender_label || "Research brief";
  return turn.sender_label || turn.sender_sandbox || "Parent agent";
}

function turnStateLabel(turn: ChatTurn) {
  if (turn.status === "queued") return "Queued";
  if (turn.status === "running") return "Working";
  if (turn.status === "interrupting") return "Interrupting";
  if (turn.status === "interrupted") return "Interrupted";
  if (turn.status === "failed") return "Failed";
  return "Completed";
}

function ToolBlock({ tool }: { tool: ToolPart }) {
  return (
    <details className="chat-tool-block">
      <summary>
        <Code2 size={13} />
        <span>{tool.title}</span>
        <small>{tool.status.replaceAll("_", " ")}</small>
        <ChevronDown size={12} />
      </summary>
      {tool.input !== undefined ? <pre>{JSON.stringify(tool.input, null, 2)}</pre> : null}
      {tool.content ? <pre>{tool.content}</pre> : null}
    </details>
  );
}

function TurnBlock({
  turn,
  events,
  onRetry,
}: {
  turn: ChatTurn;
  events: ChatEvent[];
  onRetry: (turn: ChatTurn) => void;
}) {
  const parts = foldParts(events);
  const active = turn.status === "running" || turn.status === "interrupting";
  return (
    <article className={`chat-turn chat-turn-${turn.status}`}>
      <div className="chat-user-message">
        <div className="chat-message-meta">
          <strong>{senderName(turn)}</strong>
          <span>{formatTime(turn.created_at)}</span>
        </div>
        <p>{turn.display_prompt}</p>
        <small className={`turn-state turn-state-${turn.status}`}>
          {turn.mode === "interrupt" ? <Zap size={10} /> : null}
          {turnStateLabel(turn)}
        </small>
      </div>

      <div className="chat-agent-response">
        {parts.reasoning ? (
          <details className="chat-reasoning" open={active}>
            <summary>
              <Brain size={13} />
              <span>{active ? "Thinking…" : "Reasoning"}</span>
              <ChevronDown size={12} />
            </summary>
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{parts.reasoning}</ReactMarkdown>
            </div>
          </details>
        ) : null}

        {parts.tools.map((tool) => <ToolBlock key={tool.id} tool={tool} />)}

        {parts.text ? (
          <div className="chat-assistant-message markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{parts.text}</ReactMarkdown>
            <span>{formatTime(turn.finished_at ?? turn.started_at)}</span>
          </div>
        ) : active || turn.status === "queued" ? (
          <div className="chat-planning-placeholder">
            <span className="shimmer">
              {turn.status === "queued" ? "Waiting for the current turn…" : "Planning next steps…"}
            </span>
          </div>
        ) : null}

        {turn.status === "interrupted" ? (
          <p className="chat-turn-note">This turn was interrupted. Any partial response above was preserved.</p>
        ) : null}
        {turn.status === "failed" ? (
          <div className="chat-turn-error" role="alert">
            <span>{turn.error || "The agent turn failed."}</span>
            <button type="button" onClick={() => onRetry(turn)}>
              <RotateCcw size={12} /> Retry
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function Composer({
  agent,
  busy,
  queued,
  onSend,
}: {
  agent: Agent;
  busy: boolean;
  queued: number;
  onSend: (body: string, mode: "queue" | "interrupt") => void;
}) {
  const [draft, setDraft] = useState("");

  function submit(mode: "queue" | "interrupt") {
    const body = draft.trim();
    if (!body || !agent.sandboxName) return;
    setDraft("");
    onSend(body, mode);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submit("queue");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <div className="chat-composer-shell">
      {busy || queued ? (
        <div className="composer-run-state">
          <Radio size={11} />
          {busy ? "Agent is working" : "Agent is idle"}
          {queued ? <span>{queued} queued</span> : null}
        </div>
      ) : null}
      <form className="chat-composer" onSubmit={handleSubmit}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          aria-label={`Message ${agent.name}`}
          placeholder={!agent.sandboxName ? "No live sandbox is registered for this agent" : "Steer this agent…"}
          disabled={!agent.sandboxName}
          rows={2}
        />
        <div className="chat-composer-toolbar">
          <span className="composer-hint">Enter to queue · Shift+Enter for a new line</span>
          <div>
            {busy ? (
              <button
                type="button"
                className="interrupt-button"
                disabled={!draft.trim()}
                onClick={() => submit("interrupt")}
              >
                <Zap size={12} /> Interrupt &amp; steer
              </button>
            ) : null}
            <button className="send-button" type="submit" disabled={!agent.sandboxName || !draft.trim()}>
              <ArrowUp size={16} />
              <span>{busy ? "Queue" : "Send"}</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

export function AgentChat({ project, agent }: { project: Project; agent: Agent }) {
  const dispatch = useResearchDispatch();
  const { selection } = useResearchState();
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairError, setRepairError] = useState<string | null>(null);
  const didInitialScroll = useRef(false);
  const consumedMessages = useRef(new Set<string>());
  const conversation = useAgentConversation(agent.sandboxName);
  const { scrollRef, contentRef, isAtBottom, scrollToBottom } = useStickToBottom({
    initial: "instant",
    resize: "instant",
  });

  useEffect(() => {
    if (selection.type !== "agent" || selection.agentId !== agent.id) return;
    const { initialMessage: initial, projectId, agentId } = selection;
    if (!initial || consumedMessages.current.has(initial.clientId)) return;
    consumedMessages.current.add(initial.clientId);
    conversation.send(initial.body, initial.mode, initial.clientId);
    requestAnimationFrame(() => {
      void scrollToBottom({ animation: "instant", ignoreEscapes: true, duration: 500 });
    });
    dispatch({
      type: "select",
      selection: { type: "agent", projectId, agentId },
    });
  }, [agent.id, conversation, dispatch, scrollToBottom, selection]);

  const eventsByTurn = useMemo(() => {
    const grouped = new Map<string, ChatEvent[]>();
    for (const event of conversation.events) {
      const group = grouped.get(event.turn_id) ?? [];
      group.push(event);
      grouped.set(event.turn_id, group);
    }
    return grouped;
  }, [conversation.events]);

  useEffect(() => {
    if (!conversation.hasSnapshot || didInitialScroll.current) return;
    didInitialScroll.current = true;
    const frame = requestAnimationFrame(() => {
      void scrollToBottom("instant");
    });
    return () => cancelAnimationFrame(frame);
  }, [conversation.hasSnapshot, conversation.snapshotVersion, scrollToBottom]);

  useEffect(() => {
    if (!didInitialScroll.current || !isAtBottom) return;
    void scrollToBottom({ animation: "instant", preserveScrollPosition: true });
  }, [conversation.events.length, conversation.turns.length, isAtBottom, scrollToBottom]);

  const handleSend = useCallback((body: string, mode: "queue" | "interrupt") => {
    conversation.send(body, mode);
    requestAnimationFrame(() => {
      void scrollToBottom({ animation: "instant", ignoreEscapes: true });
    });
  }, [conversation, scrollToBottom]);

  const handleRepair = useCallback(async (retryTurn?: PendingTurn) => {
    if (!agent.sandboxName || repairing) return;
    setRepairing(true);
    setRepairError(null);
    try {
      await repairAgent(agent.sandboxName);
      conversation.reconnect();
      if (retryTurn) conversation.retry(retryTurn);
    } catch (error) {
      setRepairError(error instanceof Error ? error.message : "The agent could not be repaired.");
    } finally {
      setRepairing(false);
    }
  }, [agent.sandboxName, conversation, repairing]);

  const handleRetry = useCallback((turn: PendingTurn) => {
    if (turn.deliveryCode === "runner_unavailable") {
      void handleRepair(turn);
      return;
    }
    conversation.retry(turn);
  }, [conversation, handleRepair]);

  const streamLabel = conversation.activity;
  const provisioning = project.lifecycle === "provisioning";
  const launchFailed = project.lifecycle === "failed";

  return (
    <section className="agent-chat-pane">
      <header className="agent-chat-header">
        <div className="agent-header-copy">
          <button aria-label="Open project overview" onClick={() => dispatch({ type: "select", selection: { type: "project", projectId: project.id } })}>
            <CircleGauge size={14} />
          </button>
          <div>
            <div>
              <h1>{agent.name}</h1>
              <StatusPill status={agent.status} />
              <span className={`stream-state stream-state-${streamLabel}`}><i />{streamLabel}</span>
            </div>
            <p>{project.shortName} <span>·</span> {agent.task}</p>
          </div>
        </div>
        <div className="chat-header-actions">
          <button className={diagnosticsOpen ? "active" : ""} onClick={() => setDiagnosticsOpen((open) => !open)}>
            <Terminal size={13} /> Diagnostics
          </button>
          <button className="detail-toggle" onClick={() => dispatch({ type: "toggle-detail" })}>Workspace</button>
        </div>
      </header>

      {launchFailed ? (
        <div className="agent-recovery-banner" role="alert">
          <div>
            <strong>Orchestrator launch failed</strong>
            <span>{project.lifecycleError || "The sandbox could not be provisioned."}</span>
          </div>
          <button type="button" onClick={() => dispatch({ type: "select", selection: { type: "home" } })}>
            <RotateCcw size={12} /> Retry launch
          </button>
        </div>
      ) : conversation.runtime.running === false && !provisioning ? (
        <div className="agent-recovery-banner" role="alert">
          <div>
            <strong>Agent runner is stopped</strong>
            <span>Repair it to resume the same Grok session, or stop the sandbox from Workspace.</span>
            {repairError ? <em>{repairError}</em> : null}
          </div>
          <button type="button" onClick={() => void handleRepair()} disabled={repairing}>
            <RotateCcw size={12} /> {repairing ? "Repairing…" : "Repair agent"}
          </button>
        </div>
      ) : null}

      <div ref={scrollRef} className="chat-thread" aria-live="polite">
        <div ref={contentRef} className="chat-thread-content">
          {!conversation.hasSnapshot && !provisioning ? (
            <ChatSkeleton />
          ) : provisioning && conversation.turns.length === 0 ? (
            <div className="chat-empty">
              <Radio size={18} />
              <strong>Starting the project orchestrator…</strong>
              <span>This chat is ready and will connect as soon as the sandbox comes online.</span>
            </div>
          ) : (
            <>
              {conversation.turns.length === 0 ? (
                <div className="chat-empty">
                  <Radio size={18} />
                  <strong>No turns yet</strong>
                  <span>Send guidance to start this agent’s conversation.</span>
                </div>
              ) : null}
              {conversation.turns.map((turn) => (
                <TurnBlock
                  key={turn.client_id}
                  turn={turn}
                  events={eventsByTurn.get(turn.id) ?? []}
                  onRetry={(candidate) => handleRetry(candidate as PendingTurn)}
                />
              ))}
            </>
          )}
        </div>
      </div>

      {!isAtBottom ? (
        <button
          className="chat-scroll-latest"
          type="button"
          onClick={() => void scrollToBottom({ animation: "instant", ignoreEscapes: true })}
        >
          <ArrowDown size={14} /> Latest
        </button>
      ) : null}

      {diagnosticsOpen ? (
          <aside className="chat-diagnostics">
            <header><span><Terminal size={13} /> Runner diagnostics</span><button onClick={() => setDiagnosticsOpen(false)}><X size={14} /></button></header>
            <pre>{conversation.latestLog || "No runner diagnostics have been emitted."}</pre>
          </aside>
      ) : null}

      <Composer agent={agent} busy={conversation.busy} queued={conversation.queued} onSend={handleSend} />
    </section>
  );
}
