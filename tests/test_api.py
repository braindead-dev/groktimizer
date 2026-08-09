import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from groktimizer import api
from groktimizer.core.store import Store


@pytest.fixture
def api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    config = tmp_path / "groktimizer.toml"
    config.write_text(
        """
[project]
name = "demo"
shared_repo = "https://github.com/example/research.git"
tooling_repo = "https://github.com/example/groktimizer.git"

[budget]
allowed_gpu_types = ["NVIDIA RTX PRO 6000 Blackwell Server Edition"]
""".strip()
    )
    database = tmp_path / "groktimizer.db"
    monkeypatch.setenv("GTZ_CONFIG", str(config))
    monkeypatch.setenv("GTZ_DB", str(database))
    monkeypatch.setenv("GTZ_API_TOKEN", "a" * 48)
    monkeypatch.setenv("GTZ_STREAM_SIGNING_KEY", "b" * 48)
    monkeypatch.setenv("GTZ_PUBLIC_URL", "https://api.example.test")
    return database


def authorization() -> dict[str, str]:
    return {"Authorization": f"Bearer {'a' * 48}"}


def test_health_and_authentication(api_env: Path):
    with TestClient(api.create_app()) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["schemaVersion"] == 4

        unauthorized = client.get("/v1/projects/history")
        assert unauthorized.status_code == 401
        assert unauthorized.json() == {"error": "Unauthorized"}

        authorized = client.get("/v1/projects/history", headers=authorization())
        assert authorized.status_code == 200
        assert authorized.json() == {"projects": [], "agents": []}


def test_control_plane_response_uses_backend_snapshot(
    api_env: Path, monkeypatch: pytest.MonkeyPatch
):
    async def fake_run_gtz(*args: str, timeout: float = 120):
        assert args == ("snapshot",)
        return json.dumps({"project": "demo", "projects": [], "agents": []})

    monkeypatch.setattr(api, "run_gtz", fake_run_gtz)
    with TestClient(api.create_app()) as client:
        response = client.get("/v1/control-plane", headers=authorization())
    assert response.status_code == 200
    assert response.json() == {
        "connected": True,
        "snapshot": {"project": "demo", "projects": [], "agents": []},
    }


def test_control_plane_reports_offline_without_fallback_projects(
    api_env: Path, monkeypatch: pytest.MonkeyPatch
):
    async def unavailable(*args: str, timeout: float = 120):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(api, "run_gtz", unavailable)
    with TestClient(api.create_app()) as client:
        response = client.get("/v1/control-plane", headers=authorization())
    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "mode": "offline",
        "reason": "The control plane is unavailable",
    }


def test_project_start_is_persisted_before_background_provisioning(
    api_env: Path, monkeypatch: pytest.MonkeyPatch
):
    started: list[tuple[str, str]] = []

    async def fake_provision(project: str, objective: str):
        started.append((project, objective))

    monkeypatch.setattr(api, "_provision_project", fake_provision)
    with TestClient(api.create_app()) as client:
        response = client.post(
            "/v1/projects",
            headers=authorization(),
            json={"project": "faster", "objective": "Make decoding faster"},
        )
    assert response.status_code == 202
    assert response.json()["sandbox"] == "gtz-faster-hq-main"
    assert started == [("faster", "Make decoding faster")]
    with Store(api_env) as store:
        project = next(row for row in store.list_projects() if row["name"] == "faster")
    assert project["status"] == "provisioning"
    assert project["objective"] == "Make decoding faster"


def test_stream_ticket_is_scoped_signed_and_expiring(
    api_env: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(api.time, "time", lambda: 1_000)
    ticket = api.issue_stream_ticket("gtz-demo-hq-main", ttl_seconds=60)
    api.verify_stream_ticket(ticket, "gtz-demo-hq-main")

    with pytest.raises(api.ApiError, match="Invalid or expired"):
        api.verify_stream_ticket(ticket, "gtz-demo-attn-lead")

    encoded, signature = ticket.split(".", 1)
    tampered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(api.ApiError, match="Invalid or expired"):
        api.verify_stream_ticket(f"{encoded}.{tampered_signature}", "gtz-demo-hq-main")

    monkeypatch.setattr(api.time, "time", lambda: 1_061)
    with pytest.raises(api.ApiError, match="Invalid or expired"):
        api.verify_stream_ticket(ticket, "gtz-demo-hq-main")


def test_stream_ticket_endpoint_returns_only_configured_backend_origin(api_env: Path):
    with TestClient(api.create_app()) as client:
        response = client.post(
            "/v1/agents/gtz-demo-hq-main/stream-ticket",
            headers=authorization(),
            json={"after": 7, "runtimeId": "runtime-1"},
        )
    assert response.status_code == 200
    assert response.json()["url"].startswith(
        "https://api.example.test/v1/agents/gtz-demo-hq-main/stream?"
    )
    assert "after=7" in response.json()["url"]
    assert "runtime_id=runtime-1" in response.json()["url"]


@pytest.mark.asyncio
async def test_persistent_agent_stream_replays_history_without_remote_runner(api_env: Path):
    sandbox = "gtz-demo-runtime-kernel"
    with Store(api_env) as store:
        store.upsert_project("demo", objective="Improve inference performance.")
        store.upsert_agent(
            sandbox,
            project="demo",
            team="runtime",
            name="kernel",
            role="implementer",
        )
        store.upsert_turns(
            sandbox,
            [
                {
                    "id": "turn-1",
                    "client_id": "client-1",
                    "prompt": "Validate the candidate.",
                    "display_prompt": "Validate the candidate.",
                    "mode": "queue",
                    "sender_kind": "agent",
                    "sender_sandbox": "gtz-demo-hq-main",
                    "sender_label": "Orchestrator",
                    "status": "running",
                    "created_at": "2026-08-08T20:00:00+00:00",
                    "started_at": "2026-08-08T20:00:00+00:00",
                    "finished_at": None,
                    "error": None,
                    "revision": 1,
                }
            ],
        )
        store.insert_turn_events(
            sandbox,
            [
                {
                    "id": "event-1",
                    "seq": 1,
                    "turn_id": "turn-1",
                    "type": "reasoning",
                    "payload": {"text": "Compare the candidate against the baseline."},
                    "at": "2026-08-08T20:00:01+00:00",
                }
            ],
        )
        store.set_runtime(
            sandbox,
            {
                "runtime_id": "runtime-1",
                "session_id": "session-1",
                "transport": "persistent",
                "running": True,
                "turn_status": "running",
                "active_turn_id": "turn-1",
                "queued": 0,
                "cursor": 1,
            },
        )
        store.set_event_cursor(sandbox, 1)

    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    chunks = [
        chunk
        async for chunk in api._agent_stream(  # noqa: SLF001
            DisconnectedRequest(),
            sandbox,
            0,
            None,
        )
    ]
    payload = b"".join(chunks).decode()
    assert '"type":"snapshot"' in payload
    assert '"type":"connection"' in payload
    assert '"type":"status"' in payload
    assert '"turn_status":"running"' in payload
