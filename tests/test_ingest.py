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
    with Store(tmp_path / "gtz.db") as s:
        yield s


async def test_ingest_messages_and_log(store):
    client = FakeSandboxClient()
    client.exec_responses["tail -n"] = ExecResult(
        stdout='{"id":"steer-1","role":"user","body":"go","at":"2026-01-01T00:00:00"}\n',
        exit_code=0,
    )
    client.exec_responses["wc -c"] = ExecResult(stdout="10 /var/log/gtz/session.log\n", exit_code=0)
    client.exec_responses["tail -c"] = ExecResult(stdout="0123456789", exit_code=0)

    await ingest_agent(store, client, AGENT)

    assert store.messages_for(AGENT.sandbox_name)[0]["id"] == "steer-1"
    assert store.get_log_offset(AGENT.sandbox_name) == 10
    assert "0123456789" in store.log_tail(AGENT.sandbox_name)

    # second pass with no new bytes: offset unchanged, no duplicate rows
    client.exec_responses["tail -c"] = ExecResult(stdout="", exit_code=0)
    await ingest_agent(store, client, AGENT)
    assert store.get_log_offset(AGENT.sandbox_name) == 10
    assert len(store.messages_for(AGENT.sandbox_name)) == 1


async def test_ingest_survives_exec_failure(store):
    class ExplodingClient(FakeSandboxClient):
        async def exec(self, name, command, timeout_s=120):
            raise RuntimeError("sandbox gone")

    await ingest_agent(store, ExplodingClient(), AGENT)  # must not raise
    assert store.messages_for(AGENT.sandbox_name) == []


async def test_ingest_handles_log_truncation(store):
    client = FakeSandboxClient()
    client.exec_responses["tail -n"] = ExecResult(stdout="", exit_code=0)
    store.upsert_agent(
        AGENT.sandbox_name, project="demo", team="attn", name="impl1", role="implementer"
    )
    store.set_log_offset(AGENT.sandbox_name, 100)
    # sandbox restarted: log is now smaller than our offset -> reset to 0 and re-read
    client.exec_responses["wc -c"] = ExecResult(stdout="5 /var/log/gtz/session.log\n", exit_code=0)
    client.exec_responses["tail -c"] = ExecResult(stdout="fresh", exit_code=0)
    await ingest_agent(store, client, AGENT)
    assert store.get_log_offset(AGENT.sandbox_name) == 5
