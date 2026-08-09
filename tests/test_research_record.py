from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from groktimizer.cli.main import collect_snapshot
from groktimizer.config import Config
from groktimizer.core.research_record import MetricSeriesRecord, ResearchRecord
from groktimizer.core.store import Store
from tests.fakes import FakeSandboxClient


def _history() -> list[dict]:
    turns = []
    for index in range(5):
        turns.append(
            {
                "slug": f"experiment-{index + 1}",
                "prompt": f"Run experiment {index + 1}.",
                "status": "completed",
                "started_minutes_ago": 120 - index * 20,
                "duration_minutes": 8,
                "events": [
                    {
                        "type": "reasoning",
                        "offset_seconds": 10,
                        "text": f"Plan experiment {index + 1} against the baseline.",
                    },
                    {
                        "type": "tool",
                        "offset_seconds": 60,
                        "tool": "run_trial",
                        "status": "completed",
                        "output": f"Trial {index + 1} completed with raw evidence attached.",
                    },
                    {
                        "type": "tool",
                        "offset_seconds": 120,
                        "tool": "compare_outputs",
                        "status": "completed",
                        "output": "Candidate output matches the reference digest.",
                    },
                    {
                        "type": "assistant_text",
                        "offset_seconds": 300,
                        "text": f"Experiment {index + 1} is ready for review.",
                    },
                ],
            }
        )
    turns.append(
        {
            "slug": "active-follow-up",
            "prompt": "Run the next validation slice.",
            "status": "running",
            "started_minutes_ago": 3,
            "events": [
                {
                    "type": "reasoning",
                    "offset_seconds": 10,
                    "text": "Continue from the validated checkpoint.",
                },
                {
                    "type": "tool",
                    "offset_seconds": 30,
                    "tool": "run_trial",
                    "status": "running",
                    "output": "Partial measurements are streaming.",
                },
            ],
        }
    )
    return turns


def _agent(agent_id: str, role: str) -> dict:
    return {
        "id": agent_id,
        "name": agent_id.title(),
        "role": role,
        "status": "running",
        "task": "Measure a candidate improvement.",
        "branch": f"research/{agent_id}",
        "progress": 70,
        "finding": "The candidate improves the primary metric without changing output.",
        "current_work": "Validate the candidate on a wider workload.",
        "tools": ["run_trial", "compare_outputs"],
        "history": _history(),
    }


def _record() -> ResearchRecord:
    return ResearchRecord.model_validate(
        {
            "schema_version": 1,
            "title": "Performance research",
            "source_url": "https://example.com/research",
            "projects": [
                {
                    "id": "inference",
                    "title": "Inference performance",
                    "objective": "Improve inference performance without changing output.",
                    "created_at": "Active",
                    "source_url": "https://example.com/research",
                    "hardware": "Reference accelerator",
                    "orchestrator": _agent("main", "main"),
                    "reconciler": _agent("final", "reconciler"),
                    "teams": [
                        {
                            "id": "runtime",
                            "name": "Runtime",
                            "accent": "orange",
                            "thesis": "Reduce execution overhead.",
                            "orchestrator": _agent("lead", "team"),
                            "agents": [_agent("kernel", "implementer")],
                        }
                    ],
                    "metrics": [
                        {
                            "key": "throughput",
                            "label": "Throughput",
                            "unit": "items/s",
                            "direction": "higher",
                            "accent": "orange",
                            "points": [
                                {"label": "Baseline", "value": 10, "elapsed_hours": 0},
                                {"label": "Candidate", "value": 14, "elapsed_hours": 7.5},
                            ],
                        }
                    ],
                }
            ],
        }
    )


def test_record_installs_ordered_history_idempotently(tmp_path: Path):
    record = _record()
    assert "history" in record.model_dump()["projects"][0]["orchestrator"]
    installed_at = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
    with Store(tmp_path / "research.db") as store:
        store.upsert_project("stale", objective="Old research")
        record.install(store, installed_at=installed_at, exclusive=True)
        record.install(store, installed_at=installed_at, exclusive=True)

        assert [project["name"] for project in store.list_projects()] == ["inference"]
        assert store.research_document("stale") is None
        assert len(store.list_agents("inference")) == 4
        document = store.research_document("inference")
        assert document is not None
        assert document["title"] == "Inference performance"

        for agent in store.list_agents("inference"):
            history = store.conversation_for(agent["sandbox"])
            assert len(history["turns"]) == 6
            assert len(history["events"]) == 22
            assert [event["seq"] for event in history["events"]] == list(range(1, 23))
            assert history["cursor"] == history["events"][-1]["seq"]
            assert history["turns"][-1]["status"] == "running"
            assert history["events"][-1]["payload"]["status"] == "running"
            assert history["runtime"]["transport"] == "persistent"
            assert all(
                event["payload"].get("content")
                for event in history["events"]
                if event["type"] == "tool"
            )


def test_reimport_preserves_and_rebases_live_history(tmp_path: Path):
    record = _record()
    installed_at = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
    sandbox = "gtz-inference-runtime-kernel"
    with Store(tmp_path / "research.db") as store:
        record.install(store, installed_at=installed_at)
        operator_turn = {
            "id": "operator-follow-up",
            "client_id": "operator-follow-up-client",
            "prompt": "Check another workload.",
            "display_prompt": "Check another workload.",
            "mode": "queue",
            "sender_kind": "operator",
            "sender_sandbox": None,
            "sender_label": "Operator",
            "status": "completed",
            "created_at": installed_at.isoformat(),
            "started_at": installed_at.isoformat(),
            "finished_at": installed_at.isoformat(),
            "error": None,
            "revision": 1,
        }
        store.upsert_turns(sandbox, [operator_turn])
        store.insert_turn_events(
            sandbox,
            [
                {
                    "id": "operator-follow-up-answer",
                    "seq": 23,
                    "turn_id": "operator-follow-up",
                    "type": "assistant_text",
                    "payload": {"text": "The additional workload is queued."},
                    "at": installed_at.isoformat(),
                }
            ],
        )
        store.set_event_cursor(sandbox, 23)

        record.install(store, installed_at=installed_at)

        history = store.conversation_for(sandbox)
        assert len(history["turns"]) == 7
        assert any(turn["id"] == "operator-follow-up" for turn in history["turns"])
        assert history["events"][-1]["id"] == "operator-follow-up-answer"
        assert [event["seq"] for event in history["events"]] == list(range(1, 24))
        assert history["cursor"] == 23


@pytest.mark.asyncio
async def test_record_is_exposed_by_the_control_plane_snapshot(tmp_path: Path):
    config = Config(
        project="inference",
        shared_repo="https://example.com/research.git",
        tooling_repo="https://example.com/tooling.git",
    )
    with Store(tmp_path / "research.db") as store:
        _record().install(store)
        snapshot = await collect_snapshot(config, FakeSandboxClient(), store)

    project = snapshot["projects"][0]
    assert project["project_state"]["status"] == "running"
    assert project["record"]["title"] == "Inference performance"
    assert "history" not in project["record"]["orchestrator"]
    assert "history" not in project["record"]["teams"][0]["agents"][0]


def test_metric_timelines_must_be_complete_and_strictly_increasing():
    base = {
        "key": "latency",
        "label": "Latency",
        "unit": "ms",
        "direction": "lower",
        "accent": "orange",
    }
    with pytest.raises(ValidationError, match="strictly increasing"):
        MetricSeriesRecord.model_validate(
            {
                **base,
                "points": [
                    {"label": "Baseline", "value": 100, "elapsed_hours": 0},
                    {"label": "Candidate", "value": 80, "elapsed_hours": 0},
                ],
            }
        )
    with pytest.raises(ValidationError, match="supplied for every point"):
        MetricSeriesRecord.model_validate(
            {
                **base,
                "points": [
                    {"label": "Baseline", "value": 100, "elapsed_hours": 0},
                    {"label": "Candidate", "value": 80},
                ],
            }
        )
