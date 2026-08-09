import json

import pytest

from groktimizer.config import Config
from groktimizer.core.monitor import (
    agent_status,
    repair_runtime,
    runtime_snapshot,
    send_message,
    tail_log,
)
from groktimizer.core.sandbox import ExecResult
from tests.fakes import FakeSandboxClient

NAME = "gtz-demo-attn-impl-1"


async def test_status_running_with_turn_state():
    client = FakeSandboxClient()
    client.exec_responses["tmux has-session"] = ExecResult(
        stdout=(
            "running\n"
            '{"session_id":"s1","cursor":4,"active_turn_id":"turn-1",'
            '"turn_status":"running","queued":2}\n'
            "1723123456\n"
        ),
        exit_code=0,
    )
    status = await agent_status(client, NAME)
    assert status["running"] is True
    assert status["turn_status"] == "running"
    assert status["queued"] == 2


async def test_tail():
    client = FakeSandboxClient()
    client.exec_responses["tail -n"] = ExecResult(stdout="last lines", exit_code=0)
    assert await tail_log(client, NAME, lines=5) == "last lines"


async def test_runtime_snapshot_uses_cursor():
    client = FakeSandboxClient()
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout='{"cursor":7,"turns":[],"events":[]}\n',
        exit_code=0,
    )
    result = await runtime_snapshot(client, NAME, after=4)
    assert result["cursor"] == 7
    assert "--after 4" in client.execs[-1][1]


async def test_send_queues_safely_and_is_idempotent():
    client = FakeSandboxClient()
    response = {
        "id": "turn-1",
        "client_id": "client-1",
        "prompt": "fix the bug",
        "display_prompt": "fix the bug",
        "mode": "queue",
        "sender_kind": "operator",
        "sender_sandbox": None,
        "sender_label": None,
        "status": "queued",
        "priority": 10,
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "error": None,
    }
    client.exec_responses["agent_runner.py enqueue"] = ExecResult(
        stdout=json.dumps(response) + "\n",
        exit_code=0,
    )
    message = "fix the $bug; rm -rf isn't run"
    result = await send_message(client, NAME, message, client_id="client-1")
    assert result["id"] == "turn-1"
    command = client.execs[-1][1]
    assert "--message 'fix the $bug; rm -rf isn'\"'\"'t run'" in command
    assert "--client-id client-1" in command
    assert "--resume" not in command
    assert "chat.jsonl" not in command


async def test_send_interrupt_and_provenance():
    client = FakeSandboxClient()
    response = {
        "id": "turn-2",
        "client_id": "client-2",
        "prompt": "change direction",
        "display_prompt": "change direction",
        "mode": "interrupt",
        "sender_kind": "agent",
        "sender_sandbox": "gtz-demo-hq-main",
        "sender_label": "main",
        "status": "queued",
        "priority": 0,
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "error": None,
    }
    client.exec_responses["agent_runner.py enqueue"] = ExecResult(
        stdout=json.dumps(response) + "\n",
        exit_code=0,
    )
    await send_message(
        client,
        NAME,
        "change direction",
        mode="interrupt",
        client_id="client-2",
        sender_kind="agent",
        sender_sandbox="gtz-demo-hq-main",
        sender_label="main",
    )
    command = client.execs[-1][1]
    assert "--mode interrupt" in command
    assert "--sender-sandbox gtz-demo-hq-main" in command


async def test_repair_requires_current_runtime():
    client = FakeSandboxClient()
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout='{"session_id":"old-session","cursor":0}\n', exit_code=0
    )
    with pytest.raises(RuntimeError, match="unsupported agent runner"):
        await repair_runtime(client, NAME)


async def test_repair_restarts_current_runtime_without_session_discovery():
    client = FakeSandboxClient()
    client.exec_responses["agent_runner.py export"] = ExecResult(
        stdout=(
            '{"runtime_id":"runtime-1","session_id":"session-1",'
            '"cursor":0,"turns":[],"events":[]}\n'
        ),
        exit_code=0,
    )
    result = await repair_runtime(client, NAME)
    assert result == {
        "repaired": True,
        "session_id": "session-1",
        "reinitialized": False,
    }
    assert any("--session-id session-1 --started" in command for _, command in client.execs)
    assert not any(".grok/sessions" in command for _, command in client.execs)


async def test_repair_completes_legacy_bootstrap_with_current_config():
    class LegacyClient(FakeSandboxClient):
        exports = 0

        async def exec(self, name, command, timeout_s=120):
            if "agent_runner.py export" in command:
                self.exports += 1
                if self.exports == 1:
                    return ExecResult(stdout="", exit_code=0)
                return ExecResult(
                    stdout=(
                        '{"runtime_id":"runtime-new","session_id":"session-new",'
                        '"cursor":1,"turns":[],"events":[]}\n'
                    ),
                    exit_code=0,
                )
            if "find \"$HOME/.grok/sessions" in command:
                return ExecResult(stdout="legacy-session\n", exit_code=0)
            return await super().exec(name, command, timeout_s)

    client = LegacyClient()
    cfg = Config(
        project="demo",
        shared_repo="https://github.com/o/research.git",
        tooling_repo="https://github.com/o/groktimizer.git",
    )
    result = await repair_runtime(client, NAME, cfg)
    assert result == {
        "repaired": True,
        "session_id": "session-new",
        "reinitialized": True,
    }
    assert (NAME, "/opt/gtz/agent_runner.py") in client.files
    upgrade_command = next(
        command for _, command in client.execs if "pip install --quiet" in command
    )
    assert "https://github.com/o/groktimizer.git" in upgrade_command
    assert "--session-id legacy-session --started" in upgrade_command
    assert "git checkout" not in upgrade_command
