import asyncio
import json

from groktimizer.core import agent_runner


def use_temp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_runner, "DB_PATH", tmp_path / "runtime.db")


def test_queue_priority_idempotency_and_exact_session(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    agent_runner.init_runtime("00000000-0000-4000-8000-000000000001", started=False)
    queued = agent_runner.enqueue_turn(
        prompt="first",
        display_prompt="first",
        client_id="client-1",
        turn_id="turn-1",
        mode="queue",
        sender_kind="operator",
        sender_sandbox=None,
        sender_label="You",
    )
    duplicate = agent_runner.enqueue_turn(
        prompt="ignored",
        display_prompt="ignored",
        client_id="client-1",
        turn_id="turn-other",
        mode="queue",
        sender_kind="operator",
        sender_sandbox=None,
        sender_label="You",
    )
    interrupted = agent_runner.enqueue_turn(
        prompt="urgent",
        display_prompt="urgent",
        client_id="client-2",
        turn_id="turn-2",
        mode="interrupt",
        sender_kind="agent",
        sender_sandbox="gtz-demo-hq-main",
        sender_label="main",
    )
    assert duplicate["id"] == queued["id"]
    assert interrupted["priority"] == 0

    with agent_runner.connect() as db:
        first = db.execute(
            "SELECT id FROM turns WHERE status='queued' ORDER BY priority, created_at, id LIMIT 1"
        ).fetchone()
        command = agent_runner.grok_command(db, "go")
        assert first["id"] == "turn-2"
        assert "--session-id" in command
        assert "--resume" not in command
        agent_runner.set_meta(db, "session_started", "1")
        command = agent_runner.grok_command(db, "again")
        assert "--resume" in command
        assert command[command.index("--resume") + 1] == "00000000-0000-4000-8000-000000000001"


def test_normalizes_structured_grok_updates(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    text = agent_runner.normalize_stream_event(
        {
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "done"},
                }
            },
        }
    )
    tool = agent_runner.normalize_stream_event(
        {
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "title": "Run benchmark",
                    "status": "completed",
                    "content": [{"type": "content", "content": {"type": "text", "text": "ok"}}],
                }
            },
        }
    )
    assert text == ("assistant_text", {"text": "done"})
    assert tool[0] == "tool"
    assert tool[1]["content"] == "ok"


def test_normalizes_mcp_tool_name_and_raw_output():
    call = agent_runner.normalize_stream_event(
        {
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call-1",
                    "title": "use_tool",
                    "rawInput": {
                        "tool_name": "groktimizer__list_agents",
                        "tool_input": {},
                    },
                }
            },
        }
    )
    result = agent_runner.normalize_stream_event(
        {
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "status": "completed",
                    "rawOutput": {
                        "type": "MCP",
                        "tool_name": "list_agents",
                        "output": {"OkayOutput": "attn, gemm"},
                    },
                }
            },
        }
    )
    assert call[1]["title"] == "groktimizer__list_agents"
    assert call[1]["input"] == {}
    assert result[1]["content"] == "attn, gemm"
    assert "title" not in result[1]


def test_restart_marks_inflight_turn_failed(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    agent_runner.init_runtime("session-1", started=True)
    agent_runner.enqueue_turn(
        prompt="work",
        display_prompt="work",
        client_id="client-1",
        turn_id="turn-1",
        mode="queue",
        sender_kind="operator",
        sender_sandbox=None,
        sender_label="You",
    )
    with agent_runner.connect() as db:
        db.execute("UPDATE turns SET status='running' WHERE id='turn-1'")
    assert agent_runner.recover_stale_turns() == 1
    snapshot = agent_runner.runtime_snapshot()
    assert snapshot["turns"][0]["status"] == "failed"
    assert snapshot["turns"][0]["error"] == "Runner restarted during the turn"


def test_interrupt_stops_active_turn_without_queuing_another(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    agent_runner.init_runtime("session-1", started=True)
    agent_runner.enqueue_turn(
        prompt="work",
        display_prompt="work",
        client_id="client-1",
        turn_id="turn-1",
        mode="queue",
        sender_kind="operator",
        sender_sandbox=None,
        sender_label=None,
    )
    with agent_runner.connect() as db:
        db.execute(
            "UPDATE turns SET status='running', started_at=? WHERE id='turn-1'",
            (agent_runner.now(),),
        )
    result = agent_runner.interrupt_active_turn()
    assert result == {"interrupted": True, "turn_id": "turn-1"}
    snapshot = agent_runner.runtime_snapshot()
    assert snapshot["turns"][0]["status"] == "interrupting"
    assert snapshot["queued"] == 0


async def test_grok_stream_reader_accepts_large_structured_events(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    agent_runner.init_runtime("session-1", started=True)
    agent_runner.enqueue_turn(
        prompt="work",
        display_prompt="work",
        client_id="client-1",
        turn_id="turn-1",
        mode="queue",
        sender_kind="operator",
        sender_sandbox=None,
        sender_label=None,
    )
    event = {
        "method": "session/update",
        "params": {
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call-1",
                "status": "completed",
                "rawOutput": {"output": "x" * (agent_runner.MAX_EVENT_TEXT * 2)},
            }
        },
    }
    stream = asyncio.StreamReader()
    stream.feed_data(json.dumps(event).encode() + b"\n")
    stream.feed_eof()

    class Process:
        stdout = stream

    await agent_runner.pump_output(Process(), "turn-1")
    snapshot = agent_runner.runtime_snapshot()
    payload = snapshot["events"][-1]["payload"]
    assert payload["truncated"] is True
    assert payload["preview"]


def test_runtime_id_is_stable_and_failed_turn_can_be_requeued(monkeypatch, tmp_path):
    use_temp_db(monkeypatch, tmp_path)
    first = agent_runner.init_runtime("session-1", started=True)
    turn = agent_runner.enqueue_turn(
        prompt="work",
        display_prompt="work",
        client_id="client-1",
        turn_id="turn-1",
        mode="queue",
        sender_kind="operator",
        sender_sandbox=None,
        sender_label="You",
    )
    with agent_runner.connect() as db:
        db.execute("UPDATE turns SET status='failed', error='nope' WHERE id='turn-1'")
    retried = agent_runner.enqueue_turn(
        prompt="work",
        display_prompt="work",
        client_id="client-1",
        turn_id="ignored",
        mode="queue",
        sender_kind="operator",
        sender_sandbox=None,
        sender_label="You",
        retry_existing=True,
    )
    snapshot = agent_runner.runtime_snapshot()
    assert retried["id"] == turn["id"]
    assert retried["status"] == "queued"
    assert snapshot["runtime_id"] == first["runtime_id"]
    assert retried["revision"] > turn["revision"]
