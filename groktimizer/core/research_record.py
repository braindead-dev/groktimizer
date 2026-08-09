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
    elapsed_hours: float | None = Field(default=None, ge=0)


class MetricSeriesRecord(BaseModel):
    key: str
    label: str
    unit: str
    direction: Literal["higher", "lower"]
    accent: Literal["orange", "blue", "lime", "violet"]
    points: list[MetricPointRecord] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_timeline(self) -> MetricSeriesRecord:
        elapsed = [point.elapsed_hours for point in self.points]
        if all(value is None for value in elapsed):
            return self
        if any(value is None for value in elapsed):
            raise ValueError("metric point elapsed_hours must be supplied for every point")
        defined = [value for value in elapsed if value is not None]
        if any(
            current <= previous for previous, current in zip(defined, defined[1:], strict=False)
        ):
            raise ValueError("metric point elapsed_hours must be strictly increasing")
        return self

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


class HistoryEventRecord(BaseModel):
    type: Literal["reasoning", "tool", "assistant_text"]
    offset_seconds: int = Field(ge=0)
    text: str | None = None
    tool: str | None = None
    status: Literal["running", "completed"] | None = None
    output: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> HistoryEventRecord:
        if self.type == "tool":
            if not self.tool or not self.status or not self.output:
                raise ValueError("tool history requires tool, status, and output")
        elif not self.text:
            raise ValueError(f"{self.type} history requires text")
        return self


class HistoryTurnRecord(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    prompt: str = Field(min_length=1)
    status: Literal["running", "completed"]
    started_minutes_ago: int = Field(ge=0)
    duration_minutes: int | None = Field(default=None, ge=0)
    events: list[HistoryEventRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_events(self) -> HistoryTurnRecord:
        offsets = [event.offset_seconds for event in self.events]
        if any(
            current <= previous for previous, current in zip(offsets, offsets[1:], strict=False)
        ):
            raise ValueError("history event offsets must be strictly increasing")
        if self.status == "completed" and self.duration_minutes is None:
            raise ValueError("completed history turns require duration_minutes")
        if self.status == "running" and self.duration_minutes is not None:
            raise ValueError("running history turns cannot have duration_minutes")
        return self


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
    history: list[HistoryTurnRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_history(self) -> AgentRecord:
        slugs = [turn.slug for turn in self.history]
        if len(slugs) != len(set(slugs)):
            raise ValueError("history turn slugs must be unique per agent")
        offsets = [turn.started_minutes_ago for turn in self.history]
        if any(
            current >= previous for previous, current in zip(offsets, offsets[1:], strict=False)
        ):
            raise ValueError("history turns must be ordered from oldest to newest")
        running = [index for index, turn in enumerate(self.history) if turn.status == "running"]
        if len(running) > 1 or (running and running[0] != len(self.history) - 1):
            raise ValueError("only the final history turn may be running")
        return self


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


def _project_document(project: ProjectRecord) -> dict:
    """Return project topology without duplicating per-agent conversation history."""
    document = project.model_dump(exclude_none=True)
    document["orchestrator"].pop("history", None)
    document["reconciler"].pop("history", None)
    for team in document["teams"]:
        team["orchestrator"].pop("history", None)
        for agent in team["agents"]:
            agent.pop("history", None)
    return document


def _turns_and_events(
    project: ProjectRecord,
    team: str,
    agent: AgentRecord,
    base: datetime,
) -> tuple[list[dict], list[dict], dict]:
    sandbox = _sandbox(project.id, team, agent.id)
    sender_sandbox = _sandbox(project.id, "hq", "main")
    turns: list[dict] = []
    events: list[dict] = []
    sequence = 1
    active_id: str | None = None
    for spec in agent.history:
        turn_id = f"{sandbox}-record-{spec.slug}"
        created_at = base - timedelta(minutes=spec.started_minutes_ago)
        finished_at = (
            min(created_at + timedelta(minutes=spec.duration_minutes), base)
            if spec.duration_minutes is not None
            else None
        )
        if spec.status == "running":
            active_id = turn_id
        turns.append(
            {
                "id": turn_id,
                "client_id": f"{turn_id}-client",
                "prompt": spec.prompt,
                "display_prompt": spec.prompt,
                "mode": "queue",
                "sender_kind": "agent",
                "sender_sandbox": sender_sandbox,
                "sender_label": "Orchestrator",
                "status": spec.status,
                "created_at": created_at.isoformat(),
                "started_at": created_at.isoformat(),
                "finished_at": finished_at.isoformat() if finished_at is not None else None,
                "error": None,
                "revision": 2,
            }
        )
        for event_index, event in enumerate(spec.events):
            payload: dict[str, str] = {}
            if event.type == "tool":
                payload = {
                    "toolCallId": f"{turn_id}-tool-call-{event_index}",
                    "title": event.tool or "",
                    "status": event.status or "completed",
                    "content": event.output or "",
                }
            else:
                payload = {"text": event.text or ""}
            events.append(
                {
                    "id": f"{turn_id}-event-{event_index}",
                    "seq": sequence,
                    "turn_id": turn_id,
                    "type": event.type,
                    "payload": payload,
                    "at": (created_at + timedelta(seconds=event.offset_seconds)).isoformat(),
                }
            )
            sequence += 1
    runtime = {
        "runtime_id": f"runtime-{project.id}-{team}-{agent.id}",
        "session_id": f"session-{project.id}-{team}-{agent.id}",
        "turn_status": "running" if active_id else "idle",
        "active_turn_id": active_id,
        "queued": 0,
        "running": active_id is not None,
        "transport": "persistent",
        "cursor": sequence - 1,
    }
    return turns, events, runtime


def _install_project(
    store: Store,
    record: ResearchRecord,
    project: ProjectRecord,
    installed_at: datetime,
) -> None:
    stored_document = store.research_document(project.id) or {}
    record_installed_at = stored_document.get("record_installed_at")
    history_base = installed_at
    if isinstance(record_installed_at, str):
        try:
            history_base = datetime.fromisoformat(record_installed_at)
        except ValueError:
            pass
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
                **_project_document(project),
                "program_title": record.title,
                "record_source_url": record.source_url,
                "record_installed_at": history_base.isoformat(),
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
        turns, events, runtime = _turns_and_events(project, team, agent, history_base)
        turn_prefix = f"{sandbox}-record-"
        existing = store.conversation_for(sandbox)
        legacy_turn_ids = (
            f"{sandbox}-evidence",
            f"{sandbox}-active",
            f"{sandbox}-turn-completed",
            f"{sandbox}-turn-active",
        )
        has_live_history = any(
            not turn["id"].startswith(turn_prefix) and turn["id"] not in legacy_turn_ids
            for turn in existing["turns"]
        )
        cursor = store.prepare_record_history(
            sandbox,
            turn_prefix,
            len(events),
            legacy_turn_ids=legacy_turn_ids,
        )
        store.upsert_turns(sandbox, turns)
        store.insert_turn_events(sandbox, events)
        runtime["cursor"] = cursor
        if has_live_history and existing["runtime"]:
            runtime = {**existing["runtime"], "cursor": cursor}
        store.set_runtime(sandbox, runtime)
