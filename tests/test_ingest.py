import json
from pathlib import Path

import pytest

from groktimizer.core.ingest import ingest_agent
from groktimizer.core.registry import AgentInfo
from groktimizer.core.sandbox import ExecResult
from groktimizer.core.store import Store
from tests.fakes import FakeSandboxClient

AGENT = AgentInfo(
    project="demo",
    team="attn",
    agent="impl1",
    role="implementer",
    sandbox_name="gtz-demo-attn-impl1",
)


@pytest.fixture
def store(tmp_path: Path):
    with Store(tmp_path / "gtz.db") as value:
        yield value


def runtime_payload():
    return {
        "session_id": "session-1",
        "runtime_id": "runtime-1",
        "cursor": 2,
        "active_turn_id": None,
        "turn_status": "idle",
        "queued": 0,
        "turns": [
            {
                "id": "turn-1",
                "client_id": "client-1",
                "prompt": "full prompt",
                "display_prompt": "go",
                "mode": "queue",
                "sender_kind": "operator",
                "sender_sandbox": None,
                "sender_label": "You",
                "status": "completed",
                "priority": 10,
                "created_at": "2026-01-01T00:00:00",
                "started_at": "2026-01-01T00:00:01",
                "finished_at": "2026-01-01T00:00:02",
                "error": None,
                "revision": 2,
            }
        ],
        "events": [
            {
                "id": "event-2",
                "seq": 2,
                "turn_id": "turn-1",
                "type": "assistant_text",
                "payload": {"text": "done"},
                "at": "2026-01-01T00:00:02",
            }
        ],
    }


async def test_ingest_structured_turns(store):
    client = FakeSandboxClient()
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout=json.dumps(runtime_payload()) + "\n",
        exit_code=0,
    )

    await ingest_agent(store, client, AGENT)
    conversation = store.conversation_for(AGENT.sandbox_name)
    assert conversation["turns"][0]["id"] == "turn-1"
    assert conversation["events"][0]["payload"] == {"text": "done"}
    assert conversation["cursor"] == 2

    await ingest_agent(store, client, AGENT)
    assert len(store.conversation_for(AGENT.sandbox_name)["events"]) == 1


async def test_ingest_survives_exec_failure(store):
    class ExplodingClient(FakeSandboxClient):
        async def exec(self, name, command, timeout_s=120):
            raise RuntimeError("sandbox gone")

    await ingest_agent(store, ExplodingClient(), AGENT)
    assert store.conversation_for(AGENT.sandbox_name)["turns"] == []


async def test_ingest_rejects_legacy_runner_without_upgrading(store):
    client = FakeSandboxClient()
    payload = runtime_payload()
    payload.pop("runtime_id")
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout=json.dumps(payload) + "\n", exit_code=0
    )
    error = await ingest_agent(store, client, AGENT)
    assert error == "unsupported legacy agent runner; recreate the sandbox"
    assert not client.files


async def test_ingest_requests_only_new_events(store):
    client = FakeSandboxClient()
    payload = runtime_payload()
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout=json.dumps(payload) + "\n",
        exit_code=0,
    )
    await ingest_agent(store, client, AGENT)
    await ingest_agent(store, client, AGENT)
    assert any("--after 2" in command for _, command in client.execs)


async def test_ingest_resets_when_runtime_database_is_recreated(store):
    client = FakeSandboxClient()
    first = runtime_payload()
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout=json.dumps(first) + "\n", exit_code=0
    )
    await ingest_agent(store, client, AGENT)

    second = runtime_payload()
    second["runtime_id"] = "runtime-2"
    second["cursor"] = 1
    second["events"][0]["id"] = "replacement-event"
    second["events"][0]["seq"] = 1
    second["turns"][0]["revision"] = 1
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout=json.dumps(second) + "\n", exit_code=0
    )
    await ingest_agent(store, client, AGENT)

    conversation = store.conversation_for(AGENT.sandbox_name)
    assert conversation["runtime_id"] == "runtime-2"
    assert [event["id"] for event in conversation["events"]] == ["replacement-event"]
