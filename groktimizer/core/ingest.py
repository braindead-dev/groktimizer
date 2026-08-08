"""Pull chat messages and session-log deltas from agent sandboxes into the store.

Piggybacks on existing polling (gtz snapshot every 10s from the UI; gtz watch at
1s while a chat is open) — no separate daemon. Ingest failures never propagate:
a dead sandbox just yields nothing this tick.
"""

from groktimizer.core import monitor
from groktimizer.core.registry import AgentInfo
from groktimizer.core.sandbox import SandboxClient
from groktimizer.core.store import Store

MAX_CHUNK_BYTES = 64_000


async def ingest_agent(store: Store, client: SandboxClient, agent: AgentInfo) -> None:
    sandbox = agent.sandbox_name
    store.upsert_agent(sandbox, project=agent.project, team=agent.team,
                       name=agent.agent, role=agent.role)
    try:
        messages = await monitor.tail_messages(client, sandbox, lines=200)
        if messages:
            store.insert_messages(
                [{**message, "sandbox": sandbox} for message in messages]
            )

        size_result = await client.exec(
            sandbox, f"wc -c {monitor.LOG} 2>/dev/null || echo 0"
        )
        size_token = size_result.stdout.split()[0] if size_result.stdout.split() else "0"
        log_size = int(size_token) if size_token.isdigit() else 0
        offset = store.get_log_offset(sandbox)
        if log_size < offset:
            offset = 0  # log truncated (sandbox restart): re-read from the start
        if log_size > offset:
            span = min(log_size - offset, MAX_CHUNK_BYTES)
            chunk = await client.exec(
                sandbox, f"tail -c +{offset + 1} {monitor.LOG} | head -c {span}"
            )
            if chunk.stdout:
                store.append_log_chunk(sandbox, chunk.stdout)
            store.set_log_offset(sandbox, offset + span)
        elif log_size != store.get_log_offset(sandbox):
            store.set_log_offset(sandbox, log_size)
    except Exception:
        return  # sandbox unreachable this tick; next poll retries
