from datetime import UTC, datetime
from pathlib import Path

import pytest

from groktimizer.cli.main import collect_snapshot
from groktimizer.config import Config
from groktimizer.core.research_record import ResearchRecord
from groktimizer.core.store import Store
from tests.fakes import FakeSandboxClient


def test_grok2_record_installs_idempotently(tmp_path: Path):
    record = ResearchRecord.from_path(Path("research/grok2-program.json"))
    with Store(tmp_path / "research.db") as store:
        installed_at = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
        store.upsert_project("stale", objective="Old research")
        record.install(store, installed_at=installed_at, exclusive=True)
        record.install(store, installed_at=installed_at, exclusive=True)

        projects = store.list_projects()
        assert [project["name"] for project in projects] == [
            "grok2performance",
            "grok2vision",
        ]
        assert store.research_document("stale") is None
        assert [len(store.list_agents(project["name"])) for project in projects] == [14, 14]
        document = store.research_document("grok2performance")
        assert document is not None
        assert document["title"] == "Optimize Grok 2"
        assert len(document["metrics"]) == 2

        conversation = store.conversation_for("gtz-grok2performance-speculation-ngram")
        assert len(conversation["turns"]) == 2
        assert conversation["turns"][-1]["status"] == "running"
        assert conversation["events"][-1]["payload"]["status"] == "running"
        assert conversation["runtime"]["transport"] == "persistent"


@pytest.mark.asyncio
async def test_record_is_exposed_by_the_control_plane_snapshot(tmp_path: Path):
    record = ResearchRecord.from_path(Path("research/grok2-program.json"))
    config = Config(
        project="grok2performance",
        shared_repo="https://github.com/trisanths/grokoptimizer.git",
        tooling_repo="https://github.com/braindead-dev/groktimizer.git",
    )
    with Store(tmp_path / "research.db") as store:
        record.install(store)
        snapshot = await collect_snapshot(config, FakeSandboxClient(), store)

    projects = {project["project"]: project for project in snapshot["projects"]}
    assert projects["grok2performance"]["project_state"]["status"] == "running"
    assert projects["grok2performance"]["record"]["title"] == "Optimize Grok 2"
    assert projects["grok2vision"]["record"]["title"] == "Grok 2 Vision"
