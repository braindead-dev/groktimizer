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


async def test_tail_messages_ignores_invalid_lines_and_defaults_role():
    client = FakeSandboxClient()
    client.exec_responses["tail -n"] = ExecResult(
        stdout=(
            '{"id":"steer-1","body":"hello","at":"2026-08-08T12:00:00Z"}\n'
            "not-json\n"
            '{"id":"reply-1","role":"agent","body":"done","at":"2026-08-08T12:00:05Z"}\n'
        ),
        exit_code=0,
    )
    assert await tail_messages(client, NAME) == [
        {"id": "steer-1", "role": "user", "body": "hello", "at": "2026-08-08T12:00:00Z"},
        {"id": "reply-1", "role": "agent", "body": "done", "at": "2026-08-08T12:00:05Z"},
    ]


async def test_send_quotes_message():
    client = FakeSandboxClient()
    message = "fix the $bug; rm -rf isn't run"
    message_id = await send_message(client, NAME, message)
    assert message_id.startswith("steer-")
    _, cmd = client.execs[-1]
    tmux_command = shlex.split(cmd.split("tmux new-session", 1)[1])
    resume_command = shlex.split(tmux_command[-1])
    assert resume_command[-1] == message
    assert "--continue" in cmd
    assert "tmux kill-session" in cmd
    assert "tmux new-session" in cmd
    assert "/var/log/gtz/chat.jsonl" in cmd
    assert "GIT_ASKPASS" in cmd
    # the steering record carries the user role and the returned id
    assert '"role":"user"' in cmd
    assert message_id in cmd


async def test_send_captures_agent_reply():
    client = FakeSandboxClient()
    await send_message(client, NAME, "status?")
    _, cmd = client.execs[-1]
    # the resumed grok run must tee its stdout and append it as a reply-* chat record
    assert "reply-" in cmd
    assert "tee -a /var/log/gtz/session.log" in cmd
