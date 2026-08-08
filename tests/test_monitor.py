import shlex

from groktimizer.core.monitor import agent_status, send_message, tail_log
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


async def test_send_quotes_message():
    client = FakeSandboxClient()
    await send_message(client, NAME, "fix the $bug; rm -rf isn't run")
    _, cmd = client.execs[-1]
    assert shlex.quote("fix the $bug; rm -rf isn't run") in cmd
    assert "--continue" in cmd
