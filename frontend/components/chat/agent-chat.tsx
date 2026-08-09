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
  Square,
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
import { interruptAgent, repairAgent } from "@/lib/control-plane-client";
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

type ConversationBlock =
  | { id: string; type: "text" | "reasoning"; content: string }
  | { id: string; type: "tools"; tools: ToolPart[] };

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

function conversationBlocks(events: ChatEvent[]): ConversationBlock[] {
  const blocks: ConversationBlock[] = [];
  const tools = new Map<string, ToolPart>();
  for (const event of [...events].sort((left, right) => left.seq - right.seq)) {
    if (event.type === "assistant_text" || event.type === "reasoning") {
      const type = event.type === "assistant_text" ? "text" : "reasoning";
      const content = payloadText(event);
      if (!content) continue;
      const previous = blocks.at(-1);
      if (previous?.type === type) {
        previous.content = mergeChunk(previous.content, content);
      } else {
        blocks.push({ id: event.id, type, content });
      }
      continue;
    }
    if (event.type !== "tool") continue;
    const id = typeof event.payload.toolCallId === "string" ? event.payload.toolCallId : event.id;
    const previous = tools.get(id);
    if (previous) {
      previous.title = typeof event.payload.title === "string" ? event.payload.title : previous.title;
      previous.status = typeof event.payload.status === "string" ? event.payload.status : previous.status;
      previous.content = mergeChunk(
        previous.content,
        typeof event.payload.content === "string" ? event.payload.content : "",
      );
      previous.input = event.payload.input ?? previous.input;
      continue;
    }
    const tool = {
      id,
      title: typeof event.payload.title === "string" ? event.payload.title : "Tool call",
      status: typeof event.payload.status === "string" ? event.payload.status : "pending",
      content: typeof event.payload.content === "string" ? event.payload.content : "",
      input: event.payload.input,
    };
    tools.set(id, tool);
    const last = blocks.at(-1);
    if (last?.type === "tools") last.tools.push(tool);
    else blocks.push({ id: event.id, type: "tools", tools: [tool] });
  }
  return blocks;
}

function senderName(turn: ChatTurn) {
  if (turn.sender_kind === "operator") return "You";
  if (turn.sender_kind === "system") return turn.sender_label || "Research brief";
  return turn.sender_label || turn.sender_sandbox || "Parent agent";
}

function turnStateLabel(turn: ChatTurn) {
  if (turn.status === "queued") return "Waiting";
  if (turn.status === "running") return "Working";
  if (turn.status === "interrupting") return "Interrupting";
  if (turn.status === "interrupted") return "Interrupted";
  if (turn.status === "failed") return "Failed";
  return "Completed";
}

function ToolBlock({ tool }: { tool: ToolPart }) {
  const label = tool.title
    .replace(/^groktimizer__/, "")
    .replaceAll("_", " ");
  return (
    <details className="chat-tool-block">
      <summary>
        <Code2 size={13} />
        <span>{label}</span>
        <small>{tool.status.replaceAll("_", " ")}</small>
        <ChevronDown size={12} />
      </summary>
      <div className="chat-tool-details">
        <section>
          <span>Response</span>
          <pre>{tool.content || "No response was recorded for this tool call."}</pre>
        </section>
        {tool.input !== undefined ? (
          <section>
            <span>Input</span>
            <pre>{JSON.stringify(tool.input, null, 2)}</pre>
          </section>
        ) : null}
      </div>
    </details>
  );
}

function ToolGroup({ tools }: { tools: ToolPart[] }) {
  const completed = tools.filter((tool) => tool.status === "completed").length;
  return (
    <details className="chat-tool-group">
      <summary>
        <Code2 size={13} />
        <span>{tools.length} tool {tools.length === 1 ? "call" : "calls"}</span>
        <small>{completed === tools.length ? "Completed" : `${completed}/${tools.length} complete`}</small>
        <ChevronDown size={12} />
      </summary>
      <div className="chat-tool-list">
        {tools.map((tool) => <ToolBlock key={tool.id} tool={tool} />)}
      </div>
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
  const blocks = conversationBlocks(events);
  const active = turn.status === "running" || turn.status === "interrupting";
  return (
    <article className={`chat-turn chat-turn-${turn.status}`}>
      <div className="chat-user-message">
        <p>{turn.display_prompt}</p>
        <small className={`turn-state turn-state-${turn.status}`}>
          {turn.sender_kind !== "operator" ? <span>{senderName(turn)} · </span> : null}
          {turn.mode === "interrupt" ? <Zap size={10} /> : null}
          <span className={turn.status === "queued" ? "chat-state-shimmer" : undefined}>{turnStateLabel(turn)}</span>
          <span> · {formatTime(turn.created_at)}</span>
        </small>
      </div>

      <div className="chat-agent-response">
        {blocks.map((block) => {
          if (block.type === "tools") return <ToolGroup key={block.id} tools={block.tools} />;
          if (block.type === "reasoning") {
            return (
              <details className="chat-reasoning" open={active} key={block.id}>
                <summary>
                  <Brain size={13} />
                  <span className={active ? "chat-state-shimmer" : undefined}>{active ? "Thinking…" : "Reasoning"}</span>
                  <ChevronDown size={12} />
                </summary>
                <div className="markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.content}</ReactMarkdown>
                </div>
              </details>
            );
          }
          return (
            <div className="chat-assistant-message markdown-body" key={block.id}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.content}</ReactMarkdown>
            </div>
          );
        })}

        {blocks.length === 0 && (active || turn.status === "queued") ? (
          <div className="chat-planning-placeholder">
            <span className="chat-state-shimmer">{turn.status === "queued" ? "Waiting to run…" : "Working…"}</span>
          </div>
        ) : null}

        {blocks.length ? (
          <span className="chat-response-time">{formatTime(turn.finished_at ?? turn.started_at)}</span>
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
  onStop,
  stopping,
  stopError,
}: {
  agent: Agent;
  busy: boolean;
  queued: number;
  onSend: (body: string) => void;
  onStop: () => void;
  stopping: boolean;
  stopError: string | null;
}) {
  const [draft, setDraft] = useState("");

  function submit() {
    const body = draft.trim();
    if (!body || !agent.sandboxName || busy) return;
    setDraft("");
    onSend(body);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <div className="chat-composer-shell">
      {stopError ? <div className="composer-error" role="alert">{stopError}</div> : null}
      {busy || queued ? (
        <div className="composer-run-state">
          <Radio size={11} />
          <span className="chat-state-shimmer">{busy ? "Working" : `${queued} ${queued === 1 ? "message" : "messages"} waiting`}</span>
          {busy && queued ? <span>{queued} waiting</span> : null}
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
          <span className="composer-hint">{busy ? "Stop the current response before sending" : "Enter to send · Shift+Enter for a new line"}</span>
          <div>
            {busy ? (
              <button
                type="button"
                className="stop-output-button"
                disabled={stopping}
                onClick={onStop}
              >
                <Square size={10} fill="currentColor" /> {stopping ? "Stopping…" : "Stop"}
              </button>
            ) : (
              <button className="send-button" type="submit" disabled={!agent.sandboxName || !draft.trim()}>
                <ArrowUp size={16} />
                <span>Send</span>
              </button>
            )}
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
  const [stoppingOutput, setStoppingOutput] = useState(false);
  const [stopOutputError, setStopOutputError] = useState<string | null>(null);
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

  const handleSend = useCallback((body: string) => {
    conversation.send(body, "queue");
    requestAnimationFrame(() => {
      void scrollToBottom({ animation: "instant", ignoreEscapes: true });
    });
  }, [conversation, scrollToBottom]);

  const handleStopOutput = useCallback(async () => {
    if (!agent.sandboxName || stoppingOutput) return;
    setStoppingOutput(true);
    setStopOutputError(null);
    try {
      await interruptAgent(agent.sandboxName);
    } catch (error) {
      setStopOutputError(error instanceof Error ? error.message : "The active response could not be stopped.");
    } finally {
      setStoppingOutput(false);
    }
  }, [agent.sandboxName, stoppingOutput]);

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
  const provisioning = project.lifecycle === "provisioning" || agent.status === "provisioning";
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
            <strong>{agent.runnerKind === "legacy" ? "Agent needs a runner upgrade" : "Agent runner is stopped"}</strong>
            <span>
              {agent.runnerKind === "legacy"
                ? "This sandbox used the legacy one-shot runtime. Upgrade it to restart from its research brief with durable chat and queue state."
                : "Repair it to resume the same Grok session, or stop the sandbox from Workspace."}
            </span>
            {repairError ? <em>{repairError}</em> : null}
          </div>
          <button type="button" onClick={() => void handleRepair()} disabled={repairing}>
            <RotateCcw size={12} /> {repairing ? "Repairing…" : agent.runnerKind === "legacy" ? "Upgrade runner" : "Repair agent"}
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

      <Composer
        agent={agent}
        busy={conversation.busy}
        queued={conversation.queued}
        onSend={handleSend}
        onStop={() => void handleStopOutput()}
        stopping={stoppingOutput}
        stopError={stopOutputError}
      />
    </section>
  );
}
