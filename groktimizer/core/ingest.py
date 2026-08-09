"""Pull structured turn and event deltas from agent sandboxes into the store.

Piggybacks on existing polling (gtz snapshot every 10s from the UI; gtz watch at
1s while a chat is open) — no separate daemon. Ingest failures never propagate:
a dead sandbox just yields nothing this tick.
"""

from groktimizer.core import monitor
from groktimizer.core.registry import AgentInfo
from groktimizer.core.sandbox import SandboxClient
from groktimizer.core.store import Store


async def ingest_agent(store: Store, client: SandboxClient, agent: AgentInfo) -> str | None:
    sandbox = agent.sandbox_name
    store.upsert_agent(
        sandbox, project=agent.project, team=agent.team, name=agent.agent, role=agent.role
    )
    try:
        cursor = store.get_event_cursor(sandbox)
        previous_runtime = store.runtime_for(sandbox)
        runtime = await monitor.runtime_snapshot(client, sandbox, after=cursor)
        if not runtime:
            return "agent runner unavailable; repair or upgrade the sandbox"
        if not runtime.get("runtime_id"):
            return "legacy agent runner detected; upgrade the sandbox"
        previous_runtime_id = previous_runtime.get("runtime_id")
        current_runtime_id = runtime.get("runtime_id")
        previous_session = previous_runtime.get("session_id")
        current_session = runtime.get("session_id")
        if (
            previous_runtime_id and current_runtime_id and previous_runtime_id != current_runtime_id
        ) or (previous_session and current_session and previous_session != current_session):
            store.reset_conversation(sandbox, str(current_runtime_id or ""))
            cursor = 0
            runtime = await monitor.runtime_snapshot(client, sandbox, after=0)
        if runtime:
            events = runtime.get("events", [])
            event_revisions: dict[str, int] = {}
            for event in events:
                event_revisions[event["turn_id"]] = max(
                    event_revisions.get(event["turn_id"], 0), int(event["seq"])
                )
            turns = [
                {
                    **turn,
                    "revision": max(
                        int(turn.get("revision", 0)),
                        event_revisions.get(turn["id"], int(runtime.get("cursor", 0))),
                    ),
                }
                for turn in runtime.get("turns", [])
            ]
            store.upsert_turns(sandbox, turns)
            store.insert_turn_events(sandbox, events)
            next_cursor = int(runtime.get("cursor", cursor))
            store.set_event_cursor(sandbox, max(cursor, next_cursor))
            store.set_runtime(
                sandbox,
                {
                    key: runtime.get(key)
                    for key in (
                        "session_id",
                        "runtime_id",
                        "active_turn_id",
                        "turn_status",
                        "queued",
                        "cursor",
                    )
                },
            )
        return None

    except Exception as error:  # noqa: BLE001 — unreachable sandboxes retry on the next poll
        return str(error)
