import shlex

from groktimizer.core.monitor import agent_status, send_message, tail_log, tail_messages
from groktimizer.core.sandbox import ExecResult
from tests.fakes import FakeSandboxClient

NAME = "gtz-demo-attn-impl-1"


async def test_status_running():
    client = FakeSandboxClient()
    client.exec_responses["tmux has-session"] = ExecResult(stdout="running\n", exit_code=0)
    status = await agent_status(client, NAME)
    assert status["running"] is True


async def test_tail():
    client = FakeSandboxClient()
    client.exec_responses["tail -n"] = ExecResult(stdout="last lines", exit_code=0)
    assert await tail_log(client, NAME, lines=5) == "last lines"


async def test_tail_messages_ignores_invalid_lines():
    client = FakeSandboxClient()
    client.exec_responses["tail -n"] = ExecResult(
        stdout='{"id":"steer-1","body":"hello","at":"2026-08-08T12:00:00Z"}\nnot-json\n',
        exit_code=0,
    )
    assert await tail_messages(client, NAME) == [
        {
            "id": "steer-1",
            "body": "hello",
            "at": "2026-08-08T12:00:00Z",
        }
    ]


async def test_send_quotes_message():
    client = FakeSandboxClient()
    message = "fix the $bug; rm -rf isn't run"
    await send_message(client, NAME, message)
    _, cmd = client.execs[-1]
    tmux_command = shlex.split(cmd.split("tmux new-session", 1)[1])
    resume_command = shlex.split(tmux_command[-1])
    assert resume_command[-1] == message
    assert "--continue" in cmd
    assert "tmux kill-session" in cmd
    assert "tmux new-session" in cmd
    assert "/var/log/gtz/chat.jsonl" in cmd
    assert "GIT_ASKPASS" in cmd
