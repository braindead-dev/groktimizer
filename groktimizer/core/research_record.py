"""Validated, durable research records for operator-facing project state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from groktimizer.core.store import Store

AgentRole = Literal["main", "team", "implementer", "reconciler"]
AgentState = Literal["running", "thinking", "complete"]


class MetricPointRecord(BaseModel):
    label: str
    value: float


class MetricSeriesRecord(BaseModel):
    key: str
    label: str
    unit: str
    direction: Literal["higher", "lower"]
    accent: Literal["orange", "blue", "lime", "violet"]
    points: list[MetricPointRecord] = Field(min_length=2)

    @property
    def baseline(self) -> float:
        return self.points[0].value

    @property
    def best(self) -> float:
        values = (point.value for point in self.points)
        return max(values) if self.direction == "higher" else min(values)


class DecisionRecord(BaseModel):
    id: str
    title: str
    detail: str
    impact: str
    state: Literal["promoted", "validating", "rejected"]
    time: str


class AgentRecord(BaseModel):
    id: str
    name: str
    role: AgentRole
    status: AgentState
    task: str
    branch: str
    progress: int = Field(ge=0, le=100)
    finding: str
    current_work: str
    tools: list[str] = Field(default_factory=list)


class TeamRecord(BaseModel):
    id: str
    name: str
    accent: Literal["orange", "blue", "lime", "violet"]
    thesis: str
    orchestrator: AgentRecord
    agents: list[AgentRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_roles(self) -> TeamRecord:
        if self.orchestrator.role != "team":
            raise ValueError("team orchestrator must have the team role")
        if any(agent.role != "implementer" for agent in self.agents):
            raise ValueError("team members must have the implementer role")
        return self


class ProjectRecord(BaseModel):
    id: str
    title: str
    objective: str
    status: Literal["running", "complete"] = "running"
    created_at: str
    source_url: str
    hardware: str
    orchestrator: AgentRecord
    reconciler: AgentRecord
    teams: list[TeamRecord] = Field(min_length=1)
    metrics: list[MetricSeriesRecord] = Field(min_length=1)
    decisions: list[DecisionRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_project(self) -> ProjectRecord:
        if self.orchestrator.role != "main":
            raise ValueError("project orchestrator must have the main role")
        if self.reconciler.role != "reconciler":
            raise ValueError("project reconciler must have the reconciler role")
        keys = [metric.key for metric in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("metric keys must be unique within a project")
        return self


class ResearchRecord(BaseModel):
    schema_version: Literal[1]
    title: str
    source_url: str
    projects: list[ProjectRecord] = Field(min_length=1)

    @classmethod
    def from_path(cls, path: Path) -> ResearchRecord:
        return cls.model_validate_json(path.read_text())

    def install(
        self,
        store: Store,
        *,
        installed_at: datetime | None = None,
        exclusive: bool = False,
    ) -> None:
        """Idempotently replace the projects represented by this record."""
        timestamp = installed_at or datetime.now(UTC)
        if exclusive:
            included = {project.id for project in self.projects}
            for existing in store.list_projects():
                if existing["name"] not in included:
                    store.delete_project(existing["name"])
        for project in self.projects:
            _install_project(store, self, project, timestamp)


def _sandbox(project: str, team: str, agent: str) -> str:
    return f"gtz-{project}-{team}-{agent}"


def _all_agents(project: ProjectRecord) -> list[tuple[str, AgentRecord]]:
    agents: list[tuple[str, AgentRecord]] = [
        ("hq", project.orchestrator),
        ("hq", project.reconciler),
    ]
    for team in project.teams:
        agents.append((team.id, team.orchestrator))
        agents.extend((team.id, agent) for agent in team.agents)
    return agents


def _turns_and_events(
    project: ProjectRecord,
    team: str,
    agent: AgentRecord,
    base: datetime,
) -> tuple[list[dict], list[dict], dict]:
    sandbox = _sandbox(project.id, team, agent.id)
    completed_id = f"{sandbox}-evidence"
    active_id = f"{sandbox}-active"
    completed_at = base - timedelta(minutes=34 - min(agent.progress // 4, 20))
    active_at = base - timedelta(minutes=3)
    turns = [
        {
            "id": completed_id,
            "client_id": f"{completed_id}-client",
            "prompt": agent.task,
            "display_prompt": agent.task,
            "mode": "queue",
            "sender_kind": "agent",
            "sender_sandbox": _sandbox(project.id, "hq", "main"),
            "sender_label": "Orchestrator",
            "status": "completed",
            "created_at": completed_at.isoformat(),
            "started_at": completed_at.isoformat(),
            "finished_at": (completed_at + timedelta(minutes=6)).isoformat(),
            "error": None,
            "revision": 2,
        },
        {
            "id": active_id,
            "client_id": f"{active_id}-client",
            "prompt": agent.current_work,
            "display_prompt": agent.current_work,
            "mode": "queue",
            "sender_kind": "agent",
            "sender_sandbox": _sandbox(project.id, "hq", "main"),
            "sender_label": "Orchestrator",
            "status": "running" if agent.status != "complete" else "completed",
            "created_at": active_at.isoformat(),
            "started_at": active_at.isoformat(),
            "finished_at": None if agent.status != "complete" else base.isoformat(),
            "error": None,
            "revision": 1,
        },
    ]
    events: list[dict] = [
        {
            "id": f"{completed_id}-reasoning",
            "seq": 1,
            "turn_id": completed_id,
            "type": "reasoning",
            "payload": {"text": f"Validated the current hypothesis against {project.hardware}."},
            "at": (completed_at + timedelta(minutes=1)).isoformat(),
        }
    ]
    sequence = 2
    for index, tool in enumerate(agent.tools):
        events.append(
            {
                "id": f"{completed_id}-tool-{index}",
                "seq": sequence,
                "turn_id": completed_id,
                "type": "tool",
                "payload": {
                    "toolCallId": f"{completed_id}-tool-call-{index}",
                    "title": tool,
                    "status": "completed",
                    "content": f"Completed successfully. Evidence attached to {agent.branch}.",
                },
                "at": (completed_at + timedelta(minutes=2 + index)).isoformat(),
            }
        )
        sequence += 1
    events.extend(
        [
            {
                "id": f"{completed_id}-answer",
                "seq": sequence,
                "turn_id": completed_id,
                "type": "assistant_text",
                "payload": {"text": agent.finding},
                "at": (completed_at + timedelta(minutes=5)).isoformat(),
            },
            {
                "id": f"{active_id}-reasoning",
                "seq": sequence + 1,
                "turn_id": active_id,
                "type": "reasoning",
                "payload": {"text": agent.current_work},
                "at": active_at.isoformat(),
            },
            {
                "id": f"{active_id}-tool",
                "seq": sequence + 2,
                "turn_id": active_id,
                "type": "tool",
                "payload": {
                    "toolCallId": f"{active_id}-tool-call",
                    "title": agent.tools[-1] if agent.tools else "run_benchmark",
                    "status": "running" if agent.status != "complete" else "completed",
                    "content": (
                        "Benchmark is active; partial measurements are streaming into "
                        "the run ledger."
                    )
                    if agent.status != "complete"
                    else "Validation complete and recorded.",
                },
                "at": (active_at + timedelta(seconds=20)).isoformat(),
            },
        ]
    )
    runtime = {
        "runtime_id": f"runtime-{project.id}-{team}-{agent.id}",
        "session_id": f"session-{project.id}-{team}-{agent.id}",
        "turn_status": "running" if agent.status != "complete" else "idle",
        "active_turn_id": active_id if agent.status != "complete" else None,
        "queued": 0,
        "running": agent.status != "complete",
        "transport": "persistent",
        "cursor": sequence + 2,
    }
    return turns, events, runtime


def _install_project(
    store: Store,
    record: ResearchRecord,
    project: ProjectRecord,
    installed_at: datetime,
) -> None:
    store.upsert_project(
        project.id,
        objective=project.objective,
        status="running" if project.status == "running" else "stopped",
        revive_deleted=True,
    )
    store.set_project_title(project.id, project.title)
    store.upsert_research_document(
        project.id,
        json.dumps(
            {
                **project.model_dump(),
                "program_title": record.title,
                "record_source_url": record.source_url,
            },
            separators=(",", ":"),
        ),
    )
    for team, agent in _all_agents(project):
        sandbox = _sandbox(project.id, team, agent.id)
        store.upsert_agent(
            sandbox,
            project=project.id,
            team=team,
            name=agent.id,
            role=agent.role,
        )
        turns, events, runtime = _turns_and_events(project, team, agent, installed_at)
        store.reset_conversation(sandbox, runtime["runtime_id"])
        store.upsert_turns(sandbox, turns)
        store.insert_turn_events(sandbox, events)
        store.set_event_cursor(sandbox, runtime["cursor"])
        store.set_runtime(sandbox, runtime)
