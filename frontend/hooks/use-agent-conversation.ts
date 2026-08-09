"use client";

import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { sendSteeringMessage, subscribeToAgent } from "@/lib/control-plane-client";
import type { AgentStreamEvent, AgentTurnStatus, ChatEvent, ChatTurn } from "@/lib/control-plane-types";

export type ConversationTransport = "connecting" | "live" | "reconnecting" | "unavailable";

export interface PendingTurn extends ChatTurn {
  deliveryCode?: string;
}

interface RuntimeState {
  running: boolean | null;
  turnStatus: AgentTurnStatus;
  activeTurnId: string | null;
  queued: number;
  sessionId: string | null;
}

interface ConversationState {
  sandbox?: string;
  runtimeId: string;
  cursor: number;
  turns: Record<string, ChatTurn>;
  events: Record<string, ChatEvent>;
  pending: Record<string, PendingTurn>;
  runtime: RuntimeState;
  transport: ConversationTransport;
  latestLog: string;
  lastHeartbeatAt: number | null;
  hasSnapshot: boolean;
  snapshotVersion: number;
}

type Action =
  | { type: "reset"; sandbox?: string }
  | { type: "server"; event: AgentStreamEvent }
  | { type: "connection"; connected: boolean }
  | { type: "send-started"; turn: PendingTurn }
  | { type: "send-acknowledged"; clientId: string; turn: ChatTurn }
  | { type: "send-failed"; clientId: string; message: string; code?: string };

const EMPTY_RUNTIME: RuntimeState = {
  running: null,
  turnStatus: "idle",
  activeTurnId: null,
  queued: 0,
  sessionId: null,
};

function initialState(sandbox?: string): ConversationState {
  return {
    sandbox,
    runtimeId: "",
    cursor: 0,
    turns: {},
    events: {},
    pending: {},
    runtime: EMPTY_RUNTIME,
    transport: sandbox ? "connecting" : "unavailable",
    latestLog: "",
    lastHeartbeatAt: null,
    hasSnapshot: false,
    snapshotVersion: 0,
  };
}

const STATUS_RANK: Record<ChatTurn["status"], number> = {
  queued: 0,
  running: 1,
  interrupting: 2,
  interrupted: 3,
  failed: 3,
  completed: 3,
};

function applyTurns(
  previous: Record<string, ChatTurn>,
  incoming: ChatTurn[],
) {
  const next = { ...previous };
  for (const turn of incoming) {
    const normalized = turn;
    const current = next[turn.id];
    if (
      !current
      || normalized.revision > current.revision
      || (
        normalized.revision === current.revision
        && STATUS_RANK[normalized.status] >= STATUS_RANK[current.status]
      )
    ) {
      next[turn.id] = normalized;
    }
  }
  return next;
}

function applyEvents(previous: Record<string, ChatEvent>, incoming: ChatEvent[]) {
  const next = { ...previous };
  for (const event of incoming) next[event.id] = event;
  return next;
}

function reconcilePending(
  pending: Record<string, PendingTurn>,
  turns: Record<string, ChatTurn>,
) {
  const acknowledged = new Set(Object.values(turns).map((turn) => turn.client_id));
  return Object.fromEntries(
    Object.entries(pending).filter(([clientId]) => !acknowledged.has(clientId)),
  );
}

export function conversationReducer(state: ConversationState, action: Action): ConversationState {
  if (action.type === "reset") return initialState(action.sandbox);
  if (action.type === "connection") {
    return {
      ...state,
      transport: action.connected ? "live" : state.sandbox ? "reconnecting" : "unavailable",
    };
  }
  if (action.type === "send-started") {
    return {
      ...state,
      pending: { ...state.pending, [action.turn.client_id]: action.turn },
    };
  }
  if (action.type === "send-acknowledged") {
    const turns = applyTurns(state.turns, [action.turn]);
    const pending = { ...state.pending };
    delete pending[action.clientId];
    return { ...state, turns, pending };
  }
  if (action.type === "send-failed") {
    const pending = state.pending[action.clientId];
    if (!pending) return state;
    return {
      ...state,
      pending: {
        ...state.pending,
        [action.clientId]: {
          ...pending,
          status: "failed",
          error: action.message,
          deliveryCode: action.code,
        },
      },
    };
  }

  const event = action.event;
  if (event.type === "connection") return { ...state, transport: "live" };
  if (event.type === "heartbeat") {
    return { ...state, lastHeartbeatAt: Date.parse(event.data.at) };
  }
  if (event.type === "log") return { ...state, latestLog: event.data.content };
  if (event.type === "error") return { ...state, transport: "reconnecting" };
  if (event.type === "status") {
    return {
      ...state,
      runtimeId: event.data.runtime_id ?? state.runtimeId,
      cursor: Math.max(state.cursor, event.data.cursor),
      runtime: {
        running: event.data.running,
        turnStatus: event.data.turn_status,
        activeTurnId: event.data.active_turn_id,
        queued: event.data.queued,
        sessionId: event.data.session_id,
      },
    };
  }

  if (event.type === "snapshot") {
    const runtimeChanged = Boolean(
      state.runtimeId && event.data.runtime_id && state.runtimeId !== event.data.runtime_id,
    );
    const turns = applyTurns(runtimeChanged ? {} : state.turns, event.data.turns);
    const events = applyEvents(runtimeChanged ? {} : state.events, event.data.events);
    return {
      ...state,
      runtimeId: event.data.runtime_id,
      cursor: event.data.cursor,
      turns,
      events,
      pending: reconcilePending(state.pending, turns),
      runtime: { ...state.runtime, sessionId: event.data.session_id },
      hasSnapshot: true,
      snapshotVersion: state.snapshotVersion + 1,
    };
  }

  if (state.runtimeId && event.data.runtime_id !== state.runtimeId) {
    const turns = applyTurns({}, event.data.turns);
    const events = applyEvents({}, event.data.events);
    return {
      ...state,
      runtimeId: event.data.runtime_id,
      cursor: event.data.cursor,
      turns,
      events,
      pending: reconcilePending(state.pending, turns),
      runtime: { ...EMPTY_RUNTIME, sessionId: event.data.session_id },
      hasSnapshot: true,
      snapshotVersion: state.snapshotVersion + 1,
    };
  }
  const turns = applyTurns(state.turns, event.data.turns);
  return {
    ...state,
    runtimeId: event.data.runtime_id,
    cursor: Math.max(state.cursor, event.data.cursor),
    turns,
    events: applyEvents(state.events, event.data.events),
    pending: reconcilePending(state.pending, turns),
    runtime: { ...state.runtime, sessionId: event.data.session_id },
    hasSnapshot: true,
  };
}

function pendingTurn(
  body: string,
  mode: "queue" | "interrupt",
  clientId: string,
): PendingTurn {
  return {
    id: `pending-${clientId}`,
    client_id: clientId,
    prompt: body,
    display_prompt: body,
    mode,
    sender_kind: "operator",
    sender_sandbox: null,
    sender_label: "You",
    status: "queued",
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    error: null,
    revision: 0,
  };
}

export function useAgentConversation(sandbox?: string) {
  const [state, dispatch] = useReducer(conversationReducer, sandbox, initialState);
  const [connectionGeneration, setConnectionGeneration] = useState(0);

  useEffect(() => {
    dispatch({ type: "reset", sandbox });
    if (!sandbox) return;
    return subscribeToAgent(
      sandbox,
      (event) => dispatch({ type: "server", event }),
      (connected) => dispatch({ type: "connection", connected }),
    );
  }, [connectionGeneration, sandbox]);

  useEffect(() => {
    if (!sandbox || !state.lastHeartbeatAt) return;
    const lastHeartbeatAt = state.lastHeartbeatAt;
    const timer = window.setInterval(() => {
      if (Date.now() - lastHeartbeatAt > 20_000) {
        dispatch({ type: "connection", connected: false });
      }
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [sandbox, state.lastHeartbeatAt]);

  const deliver = useCallback(async (turn: PendingTurn, retry = false) => {
    if (!sandbox) return;
    dispatch({ type: "send-started", turn: { ...turn, status: "queued", error: null } });
    try {
      const result = await sendSteeringMessage(
        sandbox,
        turn.prompt,
        turn.client_id,
        turn.mode,
        retry,
      );
      dispatch({ type: "send-acknowledged", clientId: turn.client_id, turn: result.turn });
    } catch (error) {
      dispatch({
        type: "send-failed",
        clientId: turn.client_id,
        message: error instanceof Error ? error.message : "Delivery could not be confirmed.",
        code: error instanceof Error && "code" in error ? String(error.code) : undefined,
      });
    }
  }, [sandbox]);

  const send = useCallback((
    body: string,
    mode: "queue" | "interrupt",
    clientId = crypto.randomUUID(),
  ) => {
    const turn = pendingTurn(body, mode, clientId);
    void deliver(turn);
    return turn;
  }, [deliver]);

  const retry = useCallback((turn: PendingTurn) => {
    void deliver(turn, true);
  }, [deliver]);
  const reconnect = useCallback(() => setConnectionGeneration((value) => value + 1), []);

  const turns = useMemo(() => {
    const canonicalClientIds = new Set(Object.values(state.turns).map((turn) => turn.client_id));
    return [
      ...Object.values(state.turns),
      ...Object.values(state.pending).filter((turn) => !canonicalClientIds.has(turn.client_id)),
    ].sort((left, right) => left.created_at.localeCompare(right.created_at) || left.id.localeCompare(right.id));
  }, [state.pending, state.turns]);

  const events = useMemo(
    () => Object.values(state.events).sort((left, right) => left.seq - right.seq),
    [state.events],
  );
  const busy = state.runtime.turnStatus === "running"
    || state.runtime.turnStatus === "interrupting"
    || turns.some((turn) => turn.status === "running" || turn.status === "interrupting");
  const queued = Math.max(
    state.runtime.queued,
    turns.filter((turn) => turn.status === "queued").length,
  );
  const activity = state.runtime.running === false
    ? "stopped"
    : busy
      ? "receiving"
      : queued
        ? "queued"
        : state.transport;

  return {
    ...state,
    turns,
    events,
    busy,
    queued,
    activity,
    send,
    retry,
    reconnect,
  };
}
