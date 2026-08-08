# Groktimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A three-layer hierarchy of grok-build agents (1 main orchestrator → ≤10 team orchestrators → ≤5 implementers/team), each in its own Blaxel sandbox, with role-gated MCP tools for spawning/monitoring and budget-capped RunPod GPU access, driven by a `gtz` CLI.

**Architecture:** No central service — the agent registry is Blaxel sandbox labels. One Python package: `core/` (Blaxel adapter, registry, bootstrap, monitor, budgeted RunPod), `mcp/` (stdio server each agent gets), `cli/` (`gtz`). All Blaxel access goes through a `SandboxClient` protocol so unit tests use a fake; only the thin adapter touches the SDK.

**Tech Stack:** Python 3.11+, uv, pydantic, typer, `mcp` (FastMCP), `blaxel`, `runpod`, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-08-08-groktimizer-design.md`

---

### Task 1: Scaffold

**Files:**
- Create: `pyproject.toml`, `groktimizer/__init__.py`, `groktimizer/core/__init__.py`, `groktimizer/mcp/__init__.py`, `groktimizer/cli/__init__.py`, `tests/__init__.py`, `groktimizer.toml.example`, `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "groktimizer"
version = "0.1.0"
description = "Hierarchical grok-build autoresearch system for GPU kernel optimization"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2",
    "typer>=0.12",
    "mcp>=1.2",
    "blaxel",
    "runpod",
]

[project.scripts]
gtz = "groktimizer.cli.main:app"

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["groktimizer"]
```

- [ ] **Step 2: Create empty `__init__.py` files, `.gitignore` (`.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `groktimizer.toml`), and `groktimizer.toml.example`:**

```toml
[project]
name = "demo"
shared_repo = "git@github.com:YOURORG/demo-kernels.git"   # work-products repo
tooling_repo = "https://github.com/YOURORG/groktimizer.git" # this repo, pip-installable
image = "blaxel/prod-base:latest"
region = "us-pdx-1"

[caps]
max_teams = 10
max_agents_per_team = 5

[budget]
spend_ceiling_usd = 25.0
max_concurrent_pods = 2
allowed_gpu_types = ["NVIDIA GeForce RTX 4090"]
max_pod_lifetime_hours = 2.0
```

- [ ] **Step 3: Verify env + commit**

Run: `uv sync && uv run pytest` — Expected: "no tests ran" (exit 5 is fine).

```bash
git add -A && git commit -m "chore: scaffold groktimizer package"
```

---

### Task 2: Config loading (`groktimizer/config.py`)

**Files:** Create `groktimizer/config.py`, `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
from pathlib import Path
from groktimizer.config import Config, load_config

TOML = """
[project]
name = "demo"
shared_repo = "git@github.com:o/r.git"
tooling_repo = "https://github.com/o/groktimizer.git"

[caps]
max_teams = 3

[budget]
spend_ceiling_usd = 10.0
allowed_gpu_types = ["NVIDIA GeForce RTX 4090"]
"""

def test_load_config(tmp_path: Path):
    p = tmp_path / "groktimizer.toml"
    p.write_text(TOML)
    cfg = load_config(p)
    assert cfg.project == "demo"
    assert cfg.caps.max_teams == 3
    assert cfg.caps.max_agents_per_team == 5  # default
    assert cfg.budget.spend_ceiling_usd == 10.0
    assert cfg.image  # has a default

def test_round_trip(tmp_path: Path):
    p = tmp_path / "groktimizer.toml"
    p.write_text(TOML)
    cfg = load_config(p)
    assert Config.model_validate_json(cfg.model_dump_json()) == cfg
```

- [ ] **Step 2: Run** `uv run pytest tests/test_config.py -v` — Expected: FAIL (ImportError)

- [ ] **Step 3: Implement**

```python
# groktimizer/config.py
"""Project configuration: caps, budgets, sandbox defaults."""
import tomllib
from pathlib import Path
from pydantic import BaseModel


class Caps(BaseModel):
    max_teams: int = 10
    max_agents_per_team: int = 5


class Budget(BaseModel):
    spend_ceiling_usd: float = 25.0
    max_concurrent_pods: int = 2
    allowed_gpu_types: list[str] = ["NVIDIA GeForce RTX 4090"]
    max_pod_lifetime_hours: float = 2.0


class Config(BaseModel):
    project: str
    shared_repo: str
    tooling_repo: str
    image: str = "blaxel/prod-base:latest"
    region: str = "us-pdx-1"
    caps: Caps = Caps()
    budget: Budget = Budget()


def load_config(path: Path) -> Config:
    data = tomllib.loads(path.read_text())
    flat = {**data.get("project", {}), "caps": data.get("caps", {}), "budget": data.get("budget", {})}
    # [project] name= maps to Config.project
    flat["project"] = flat.pop("name")
    return Config.model_validate(flat)
```

- [ ] **Step 4: Run** `uv run pytest tests/test_config.py -v` — Expected: PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: config loading with caps and budget"`

---

### Task 3: Types, naming, and SandboxClient protocol (`groktimizer/core/sandbox.py`)

**Files:** Create `groktimizer/core/sandbox.py`, `tests/test_sandbox.py`, `tests/fakes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sandbox.py
from groktimizer.core.sandbox import agent_labels, sandbox_name

def test_sandbox_name():
    assert sandbox_name("demo", "hq", "main") == "gtz-demo-hq-main"

def test_agent_labels():
    labels = agent_labels("demo", "attn", "impl-1", "implementer")
    assert labels == {
        "gtz-project": "demo", "gtz-team": "attn",
        "gtz-agent": "impl-1", "gtz-role": "implementer",
    }
```

- [ ] **Step 2: Run** `uv run pytest tests/test_sandbox.py -v` — Expected: FAIL

- [ ] **Step 3: Implement protocol + helpers**

```python
# groktimizer/core/sandbox.py
"""Sandbox naming, labels, and the client protocol all Blaxel access goes through."""
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["main", "team", "implementer"]
MAIN_TEAM = "hq"  # the main orchestrator's pseudo-team


def sandbox_name(project: str, team: str, agent: str) -> str:
    return f"gtz-{project}-{team}-{agent}"


def agent_labels(project: str, team: str, agent: str, role: Role) -> dict[str, str]:
    return {"gtz-project": project, "gtz-team": team, "gtz-agent": agent, "gtz-role": role}


@dataclass
class SandboxMeta:
    name: str
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ExecResult:
    stdout: str
    exit_code: int


class SandboxClient(Protocol):
    async def create(self, name: str, image: str, region: str,
                     labels: dict[str, str], envs: dict[str, str]) -> None: ...
    async def delete(self, name: str) -> None: ...
    async def list(self, labels: dict[str, str]) -> list[SandboxMeta]: ...
    async def exec(self, name: str, command: str, timeout_s: int = 120) -> ExecResult: ...
    async def write_file(self, name: str, path: str, content: str) -> None: ...
```

- [ ] **Step 4: Write the shared fake used by later tasks**

```python
# tests/fakes.py
"""In-memory SandboxClient fake shared across test modules."""
from groktimizer.core.sandbox import ExecResult, SandboxMeta


class FakeSandboxClient:
    def __init__(self):
        self.sandboxes: dict[str, SandboxMeta] = {}
        self.files: dict[tuple[str, str], str] = {}
        self.execs: list[tuple[str, str]] = []
        self.exec_responses: dict[str, ExecResult] = {}  # substring -> result

    async def create(self, name, image, region, labels, envs):
        self.sandboxes[name] = SandboxMeta(name=name, labels=dict(labels))

    async def delete(self, name):
        self.sandboxes.pop(name, None)

    async def list(self, labels):
        return [m for m in self.sandboxes.values()
                if all(m.labels.get(k) == v for k, v in labels.items())]

    async def exec(self, name, command, timeout_s=120):
        self.execs.append((name, command))
        for needle, result in self.exec_responses.items():
            if needle in command:
                return result
        return ExecResult(stdout="", exit_code=0)

    async def write_file(self, name, path, content):
        self.files[(name, path)] = content
```

- [ ] **Step 5: Run** `uv run pytest tests/test_sandbox.py -v` — Expected: PASS
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: sandbox naming, labels, client protocol + test fake"`

---

### Task 4: Registry with cap enforcement (`groktimizer/core/registry.py`)

**Files:** Create `groktimizer/core/registry.py`, `tests/test_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_registry.py
import pytest
from groktimizer.config import Caps
from groktimizer.core.registry import AgentInfo, CapExceededError, Registry
from groktimizer.core.sandbox import agent_labels, sandbox_name
from tests.fakes import FakeSandboxClient


async def seed(client, project, team, agent, role):
    await client.create(sandbox_name(project, team, agent), "img", "r",
                        agent_labels(project, team, agent, role), {})


@pytest.fixture
def client():
    return FakeSandboxClient()


async def test_list_teams_and_agents(client):
    await seed(client, "demo", "hq", "main", "main")
    await seed(client, "demo", "attn", "lead", "team")
    await seed(client, "demo", "attn", "impl-1", "implementer")
    await seed(client, "other", "x", "lead", "team")  # different project: excluded
    reg = Registry(client, "demo")
    assert await reg.list_teams() == ["attn"]  # hq is not a real team
    agents = await reg.list_agents(team="attn")
    assert {a.agent for a in agents} == {"lead", "impl-1"}
    assert all(isinstance(a, AgentInfo) for a in agents)


async def test_team_cap(client):
    caps = Caps(max_teams=1, max_agents_per_team=5)
    await seed(client, "demo", "attn", "lead", "team")
    reg = Registry(client, "demo")
    with pytest.raises(CapExceededError):
        await reg.ensure_can_spawn("team", "gemm", caps)
    # spawning into the EXISTING team's implementer slots is still fine
    await reg.ensure_can_spawn("implementer", "attn", caps)


async def test_agent_cap(client):
    caps = Caps(max_teams=10, max_agents_per_team=1)
    await seed(client, "demo", "attn", "impl-1", "implementer")
    reg = Registry(client, "demo")
    with pytest.raises(CapExceededError):
        await reg.ensure_can_spawn("implementer", "attn", caps)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_registry.py -v` — Expected: FAIL

- [ ] **Step 3: Implement**

```python
# groktimizer/core/registry.py
"""Live agent registry: Blaxel sandbox labels are the source of truth."""
from dataclasses import dataclass

from groktimizer.config import Caps
from groktimizer.core.sandbox import MAIN_TEAM, Role, SandboxClient


class CapExceededError(Exception):
    pass


@dataclass
class AgentInfo:
    project: str
    team: str
    agent: str
    role: Role
    sandbox_name: str


class Registry:
    def __init__(self, client: SandboxClient, project: str):
        self.client = client
        self.project = project

    async def list_agents(self, team: str | None = None) -> list[AgentInfo]:
        labels = {"gtz-project": self.project}
        if team:
            labels["gtz-team"] = team
        metas = await self.client.list(labels)
        return [
            AgentInfo(
                project=self.project,
                team=m.labels["gtz-team"],
                agent=m.labels["gtz-agent"],
                role=m.labels["gtz-role"],  # type: ignore[arg-type]
                sandbox_name=m.name,
            )
            for m in metas
        ]

    async def list_teams(self) -> list[str]:
        agents = await self.list_agents()
        return sorted({a.team for a in agents} - {MAIN_TEAM})

    async def ensure_can_spawn(self, role: Role, team: str, caps: Caps) -> None:
        if role == "main":
            raise CapExceededError("the main orchestrator is spawned by the CLI, not by agents")
        teams = await self.list_teams()
        if role == "team":
            if team in teams:
                raise CapExceededError(f"team {team!r} already has an orchestrator")
            if len(teams) >= caps.max_teams:
                raise CapExceededError(f"team cap reached ({caps.max_teams})")
        if role == "implementer":
            members = [a for a in await self.list_agents(team=team) if a.role == "implementer"]
            if len(members) >= caps.max_agents_per_team:
                raise CapExceededError(
                    f"implementer cap reached for team {team!r} ({caps.max_agents_per_team})"
                )
```

- [ ] **Step 4: Run** `uv run pytest tests/test_registry.py -v` — Expected: PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: label-based registry with live cap enforcement"`

---

### Task 5: Budgeted RunPod wrapper (`groktimizer/core/gpu.py`)

**Files:** Create `groktimizer/core/gpu.py`, `tests/test_gpu.py`

Note: module named `gpu.py` (not `runpod.py`) to avoid shadowing the `runpod` package on import.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gpu.py
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from groktimizer.config import Budget
from groktimizer.core.gpu import BudgetError, BudgetedRunPod

GPU = "NVIDIA GeForce RTX 4090"


class FakeRunpodApi:
    def __init__(self):
        self.pods: dict[str, dict] = {}
        self.n = 0

    def create_pod(self, name, image_name, gpu_type_id, **kw):
        self.n += 1
        pod = {"id": f"pod{self.n}", "name": name, "gpuTypeId": gpu_type_id}
        self.pods[pod["id"]] = pod
        return pod

    def terminate_pod(self, pod_id):
        self.pods.pop(pod_id)

    def get_gpu(self, gpu_id):
        return {"id": gpu_id, "lowestPrice": {"uninterruptablePrice": 0.60}}


@pytest.fixture
def rp():
    return FakeRunpodApi()


def mk(rp, tmp_path: Path, **budget_kw) -> BudgetedRunPod:
    budget = Budget(allowed_gpu_types=[GPU], **budget_kw)
    return BudgetedRunPod(rp, budget, tmp_path / "ledger.json")


def test_provision_and_ledger(rp, tmp_path):
    b = mk(rp, tmp_path)
    pod = b.provision("bench", "runpod/pytorch:2.4", GPU)
    assert pod["id"] in rp.pods
    assert b.current_spend_usd() >= 0
    b.terminate(pod["id"])
    assert rp.pods == {}
    # terminated pod's accrued cost persisted as completed spend
    b2 = mk(rp, tmp_path)
    assert b2.current_spend_usd() == pytest.approx(b.current_spend_usd(), abs=0.01)


def test_gpu_allowlist(rp, tmp_path):
    b = mk(rp, tmp_path)
    with pytest.raises(BudgetError, match="not in allowed"):
        b.provision("bench", "img", "NVIDIA H100 80GB HBM3")


def test_concurrency_cap(rp, tmp_path):
    b = mk(rp, tmp_path, max_concurrent_pods=1)
    b.provision("a", "img", GPU)
    with pytest.raises(BudgetError, match="concurrent"):
        b.provision("b", "img", GPU)


def test_spend_ceiling(rp, tmp_path):
    # ceiling 1.0, projected cost 0.60*2h = 1.20 > 1.0
    b = mk(rp, tmp_path, spend_ceiling_usd=1.0, max_pod_lifetime_hours=2.0)
    with pytest.raises(BudgetError, match="ceiling"):
        b.provision("a", "img", GPU)


def test_reap_expired(rp, tmp_path):
    b = mk(rp, tmp_path, max_pod_lifetime_hours=1.0)
    pod = b.provision("a", "img", GPU)
    # backdate the pod 2 hours in the ledger
    b.ledger["live"][pod["id"]]["started_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()
    b.save()
    reaped = b.reap_expired()
    assert reaped == [pod["id"]]
    assert rp.pods == {}
    assert b.current_spend_usd() == pytest.approx(1.20, abs=0.05)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_gpu.py -v` — Expected: FAIL

- [ ] **Step 3: Implement**

```python
# groktimizer/core/gpu.py
"""RunPod wrapper enforcing project GPU budget: allowlist, concurrency, spend ceiling, lifetime."""
import json
from datetime import datetime, timezone
from pathlib import Path

from groktimizer.config import Budget


class BudgetError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BudgetedRunPod:
    def __init__(self, rp, budget: Budget, ledger_path: Path):
        self.rp = rp  # the `runpod` module, or a fake in tests
        self.budget = budget
        self.ledger_path = ledger_path
        self.ledger: dict = {"completed_usd": 0.0, "live": {}}
        if ledger_path.exists():
            self.ledger = json.loads(ledger_path.read_text())

    def save(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(self.ledger, indent=2))

    def _rate(self, gpu_type: str) -> float:
        gpu = self.rp.get_gpu(gpu_type)
        return float(gpu["lowestPrice"]["uninterruptablePrice"])

    def _accrued(self, entry: dict) -> float:
        hours = (_now() - datetime.fromisoformat(entry["started_at"])).total_seconds() / 3600
        return hours * entry["cost_per_hr"]

    def current_spend_usd(self) -> float:
        return self.ledger["completed_usd"] + sum(
            self._accrued(e) for e in self.ledger["live"].values()
        )

    def provision(self, name: str, image: str, gpu_type: str, **create_kw) -> dict:
        if gpu_type not in self.budget.allowed_gpu_types:
            raise BudgetError(
                f"GPU {gpu_type!r} not in allowed types {self.budget.allowed_gpu_types}"
            )
        if len(self.ledger["live"]) >= self.budget.max_concurrent_pods:
            raise BudgetError(f"max concurrent pods reached ({self.budget.max_concurrent_pods})")
        rate = self._rate(gpu_type)
        projected = self.current_spend_usd() + rate * self.budget.max_pod_lifetime_hours
        if projected > self.budget.spend_ceiling_usd:
            raise BudgetError(
                f"projected spend ${projected:.2f} exceeds ceiling "
                f"${self.budget.spend_ceiling_usd:.2f}"
            )
        pod = self.rp.create_pod(name, image, gpu_type, **create_kw)
        self.ledger["live"][pod["id"]] = {
            "started_at": _now().isoformat(),
            "cost_per_hr": rate,
            "gpu_type": gpu_type,
        }
        self.save()
        return pod

    def terminate(self, pod_id: str) -> None:
        self.rp.terminate_pod(pod_id)
        entry = self.ledger["live"].pop(pod_id, None)
        if entry:
            self.ledger["completed_usd"] += self._accrued(entry)
        self.save()

    def reap_expired(self) -> list[str]:
        limit = self.budget.max_pod_lifetime_hours
        expired = [
            pid for pid, e in self.ledger["live"].items()
            if self._accrued(e) / e["cost_per_hr"] > limit
        ]
        for pid in expired:
            self.terminate(pid)
        return expired
```

- [ ] **Step 4: Run** `uv run pytest tests/test_gpu.py -v` — Expected: PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: budget-enforcing RunPod wrapper with persistent ledger"`

---

### Task 6: Role prompts (`groktimizer/prompts/`)

**Files:** Create `groktimizer/prompts/__init__.py`, `groktimizer/prompts/main_orchestrator.md`, `groktimizer/prompts/team_orchestrator.md`, `groktimizer/prompts/implementer.md`, `tests/test_prompts.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_prompts.py
from groktimizer.prompts import render_brief

def test_render_each_role():
    for role in ("main", "team", "implementer"):
        text = render_brief(role, project="demo", team="attn", agent="a1",
                            brief="Optimize softmax", shared_repo="git@x:y.git")
        assert "Optimize softmax" in text
        assert "demo" in text
        assert "{" not in text.replace("{{", "")  # no unfilled placeholders
```

- [ ] **Step 2: Run** `uv run pytest tests/test_prompts.py -v` — Expected: FAIL

- [ ] **Step 3: Implement renderer**

```python
# groktimizer/prompts/__init__.py
"""Role prompt templates rendered into each agent's kickoff brief."""
from importlib import resources

_FILES = {
    "main": "main_orchestrator.md",
    "team": "team_orchestrator.md",
    "implementer": "implementer.md",
}


def render_brief(role: str, *, project: str, team: str, agent: str,
                 brief: str, shared_repo: str) -> str:
    template = (resources.files("groktimizer.prompts") / _FILES[role]).read_text()
    return template.format(project=project, team=team, agent=agent,
                           brief=brief, shared_repo=shared_repo)
```

- [ ] **Step 4: Write the three templates.** Full content below; keep `{placeholders}` matching the renderer.

`main_orchestrator.md`:

```markdown
# Role: Main Orchestrator — project {project}

You are the main orchestrator of an autoresearch project optimizing GPU inference
(kernels, quantization, throughput/latency). You run headless; be decisive and autonomous.

## Your research brief
{brief}

## Your organization
- You command up to 10 teams; each team has one team orchestrator and up to 5 implementers.
- Use your `groktimizer` MCP tools: `spawn_agent` (into an existing team or a new one — your
  judgement), `list_teams`, `list_agents`, `agent_status`, `tail_agent`, `exec_in_agent`,
  `send_to_agent`, `terminate_agent`.
- Poll subordinates with `agent_status`/`tail_agent`. Respawn dead or stalled agents.
- Tool errors about caps or budget are hard limits — reprioritize instead of retrying.

## Work products
- Shared repo: {shared_repo} (cloned at /workspace/project).
- Team orchestrators merge implementer branches (`agent/<name>`) into `team/<team>` branches.
- You merge winning team branches into `main` after verifying claims (you may use
  `provision_gpu`/`run_on_gpu` to reproduce benchmarks — budget permitting).

## Method
1. Decompose the brief into team-sized workstreams (e.g. attention kernels, GEMM, quantization).
2. Spawn team orchestrators with crisp briefs and measurable success criteria.
3. Continuously monitor, reallocate, merge, and keep a RESULTS.md scoreboard on `main`.
```

`team_orchestrator.md`:

```markdown
# Role: Team Orchestrator — team {team}, project {project}

You lead one research team optimizing GPU inference. You run headless; be decisive.

## Your team's brief
{brief}

## Your team
- You may spawn up to 5 implementers IN YOUR OWN TEAM with `spawn_agent`; monitor them with
  `agent_status`/`tail_agent`/`exec_in_agent`/`send_to_agent`; `terminate_agent` the stalled.
- Give each implementer a narrow, measurable task (one kernel/technique + target metric).
- Tool errors about caps or budget are hard limits — reprioritize instead of retrying.

## Work products
- Shared repo: {shared_repo} (cloned at /workspace/project).
- Implementers push `agent/<name>` branches with code + `benchmarks/*.json`.
- VERIFY before merging: rerun their benchmark on a GPU you provision (`provision_gpu`,
  `run_on_gpu`), then merge validated work into `team/{team}` and report upward via the
  repo (update `team/{team}/REPORT.md`).
```

`implementer.md`:

```markdown
# Role: Implementer — agent {agent}, team {team}, project {project}

You are a hands-on GPU performance engineer. You run headless; be decisive.

## Your task
{brief}

## Method
- Work in the shared repo clone at /workspace/project on branch `agent/{agent}`.
- Use `provision_gpu` / `run_on_gpu` / `terminate_pod` for real hardware. Terminate pods the
  moment you finish a run — budget is shared and enforced.
- Benchmark honestly: warmups, repeats, report mean/p50/p99 into `benchmarks/<name>.json`
  with exact hardware, driver, and command lines.
- Commit and push early and often. When done (or blocked), push and write STATUS.md on your
  branch; your team orchestrator reads it.
- Budget/cap tool errors are hard limits — report them in STATUS.md instead of retrying.
```

- [ ] **Step 5: Run** `uv run pytest tests/test_prompts.py -v` — Expected: PASS

Note: `.format()` will KeyError on literal `{` in templates — templates above use `<name>` style for non-placeholder brackets deliberately; keep it that way.

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: role prompt templates + renderer"`

---

### Task 7: Bootstrap (`groktimizer/core/bootstrap.py`)

**Files:** Create `groktimizer/core/bootstrap.py`, `tests/test_bootstrap.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_bootstrap.py
from groktimizer.config import Budget, Caps, Config
from groktimizer.core.bootstrap import spawn_agent
from tests.fakes import FakeSandboxClient

CFG = Config(project="demo", shared_repo="git@x:y.git",
             tooling_repo="https://github.com/o/groktimizer.git",
             caps=Caps(), budget=Budget())


async def test_spawn_creates_configured_sandbox():
    client = FakeSandboxClient()
    name = await spawn_agent(CFG, client, team="attn", agent="impl-1",
                             role="implementer", brief="Optimize softmax",
                             extra_envs={"RUNPOD_API_KEY": "k"})
    assert name == "gtz-demo-attn-impl-1"
    meta = client.sandboxes[name]
    assert meta.labels["gtz-role"] == "implementer"
    # brief and setup script written into the sandbox
    assert "Optimize softmax" in client.files[(name, "/opt/gtz/brief.md")]
    setup = client.files[(name, "/opt/gtz/setup.sh")]
    assert "x.ai/cli/install.sh" in setup
    assert "tmux new-session" in setup
    # setup executed
    assert any("setup.sh" in cmd for _, cmd in client.execs)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_bootstrap.py -v` — Expected: FAIL

- [ ] **Step 3: Implement**

```python
# groktimizer/core/bootstrap.py
"""Provision a new agent: sandbox, grok CLI, MCP registration, kickoff session."""
from groktimizer.config import Config
from groktimizer.core.sandbox import Role, SandboxClient, agent_labels, sandbox_name
from groktimizer.prompts import render_brief

# NOTE for implementer of this task: `grok mcp add` syntax and non-interactive auth
# (XAI_API_KEY) must be verified against https://docs.x.ai/build/cli before the e2e run.
# If `grok mcp add` doesn't exist, write the MCP entry into grok's config file instead.
SETUP_SH = """#!/usr/bin/env bash
set -euxo pipefail
export PATH="$HOME/.local/bin:$PATH"
command -v tmux >/dev/null || (apt-get update -qq && apt-get install -y -qq tmux git python3-pip)
curl -fsSL https://x.ai/cli/install.sh | bash
pip install --quiet "git+${GTZ_TOOLING_REPO}"
git clone "${GTZ_SHARED_REPO}" /workspace/project 2>/dev/null || true
grok mcp add groktimizer -- python3 -m groktimizer.mcp
mkdir -p /var/log/gtz
tmux new-session -d -s gtz \\
  'grok -p --always-approve --no-auto-update --session-id gtz \\
   "$(cat /opt/gtz/brief.md)" 2>&1 | tee -a /var/log/gtz/session.log'
"""

PASSTHROUGH_ENVS = ("RUNPOD_API_KEY", "XAI_API_KEY", "BL_API_KEY", "BL_WORKSPACE")


async def spawn_agent(cfg: Config, client: SandboxClient, *, team: str, agent: str,
                      role: Role, brief: str, extra_envs: dict[str, str] | None = None) -> str:
    name = sandbox_name(cfg.project, team, agent)
    envs = {
        "GTZ_PROJECT": cfg.project,
        "GTZ_TEAM": team,
        "GTZ_AGENT": agent,
        "GTZ_ROLE": role,
        "GTZ_SHARED_REPO": cfg.shared_repo,
        "GTZ_TOOLING_REPO": cfg.tooling_repo,
        "GTZ_CONFIG_JSON": cfg.model_dump_json(),
        **(extra_envs or {}),
    }
    await client.create(name, cfg.image, cfg.region,
                        labels=agent_labels(cfg.project, team, agent, role), envs=envs)
    rendered = render_brief(role, project=cfg.project, team=team, agent=agent,
                            brief=brief, shared_repo=cfg.shared_repo)
    await client.write_file(name, "/opt/gtz/brief.md", rendered)
    await client.write_file(name, "/opt/gtz/setup.sh", SETUP_SH)
    await client.exec(name, "bash /opt/gtz/setup.sh", timeout_s=900)
    return name
```

- [ ] **Step 4: Run** `uv run pytest tests/test_bootstrap.py -v` — Expected: PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: agent bootstrap (sandbox + grok + tmux kickoff)"`

---

### Task 8: Monitor (`groktimizer/core/monitor.py`)

**Files:** Create `groktimizer/core/monitor.py`, `tests/test_monitor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_monitor.py
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
```

- [ ] **Step 2: Run** `uv run pytest tests/test_monitor.py -v` — Expected: FAIL

- [ ] **Step 3: Implement**

```python
# groktimizer/core/monitor.py
"""Observe and steer a subordinate agent through its sandbox exec channel."""
import shlex

from groktimizer.core.sandbox import SandboxClient

LOG = "/var/log/gtz/session.log"


async def agent_status(client: SandboxClient, name: str) -> dict:
    r = await client.exec(
        name, f"tmux has-session -t gtz 2>/dev/null && echo running; stat -c %Y {LOG} 2>/dev/null"
    )
    lines = r.stdout.split()
    running = "running" in lines
    mtimes = [tok for tok in lines if tok.isdigit()]
    return {"running": running, "log_mtime": int(mtimes[0]) if mtimes else None}


async def tail_log(client: SandboxClient, name: str, lines: int = 50) -> str:
    r = await client.exec(name, f"tail -n {int(lines)} {LOG}")
    return r.stdout


async def send_message(client: SandboxClient, name: str, message: str) -> None:
    quoted = shlex.quote(message)
    await client.exec(
        name,
        "bash -lc "
        + shlex.quote(
            f"nohup grok -p --continue --always-approve --no-auto-update {quoted} "
            f">> {LOG} 2>&1 &"
        ),
    )


async def exec_in_agent(client: SandboxClient, name: str, command: str, timeout_s: int = 120) -> str:
    r = await client.exec(name, command, timeout_s=timeout_s)
    return r.stdout
```

- [ ] **Step 4: Run** `uv run pytest tests/test_monitor.py -v` — Expected: PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: agent monitoring and messaging via sandbox exec"`

---

### Task 9: Role-gated MCP server (`groktimizer/mcp/server.py` + `__main__.py`)

**Files:** Create `groktimizer/mcp/server.py`, `groktimizer/mcp/__main__.py`, `tests/test_mcp_gating.py`

Design: pure policy functions are unit-tested; the FastMCP wiring reads its identity
(`GTZ_ROLE`, `GTZ_TEAM`, …) and config (`GTZ_CONFIG_JSON`) from env injected at bootstrap.

- [ ] **Step 1: Write failing tests for the policy**

```python
# tests/test_mcp_gating.py
import pytest
from groktimizer.mcp.server import PermissionError_, check_manage, check_spawn


def test_main_spawns_anywhere():
    check_spawn(actor_role="main", actor_team="hq", target_role="team", target_team="newteam")
    check_spawn(actor_role="main", actor_team="hq", target_role="implementer", target_team="attn")


def test_team_orch_spawns_only_own_implementers():
    check_spawn(actor_role="team", actor_team="attn",
                target_role="implementer", target_team="attn")
    with pytest.raises(PermissionError_):
        check_spawn(actor_role="team", actor_team="attn",
                    target_role="implementer", target_team="gemm")
    with pytest.raises(PermissionError_):
        check_spawn(actor_role="team", actor_team="attn",
                    target_role="team", target_team="new")


def test_implementer_spawns_nothing():
    with pytest.raises(PermissionError_):
        check_spawn(actor_role="implementer", actor_team="attn",
                    target_role="implementer", target_team="attn")


def test_manage_scope():
    check_manage(actor_role="main", actor_team="hq", target_team="attn")
    check_manage(actor_role="team", actor_team="attn", target_team="attn")
    with pytest.raises(PermissionError_):
        check_manage(actor_role="team", actor_team="attn", target_team="gemm")
    with pytest.raises(PermissionError_):
        check_manage(actor_role="implementer", actor_team="attn", target_team="attn")
```

- [ ] **Step 2: Run** `uv run pytest tests/test_mcp_gating.py -v` — Expected: FAIL

- [ ] **Step 3: Implement policy + server**

```python
# groktimizer/mcp/server.py
"""MCP server every agent runs; tools are gated by the agent's own role."""
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from groktimizer.config import Config
from groktimizer.core import monitor
from groktimizer.core.bootstrap import PASSTHROUGH_ENVS, spawn_agent
from groktimizer.core.gpu import BudgetedRunPod
from groktimizer.core.registry import Registry
from groktimizer.core.sandbox import Role


class PermissionError_(Exception):
    pass


def check_spawn(*, actor_role: Role, actor_team: str, target_role: Role, target_team: str) -> None:
    if actor_role == "main":
        if target_role == "main":
            raise PermissionError_("cannot spawn another main orchestrator")
        return
    if actor_role == "team":
        if target_role != "implementer" or target_team != actor_team:
            raise PermissionError_("team orchestrators may only spawn implementers in their own team")
        return
    raise PermissionError_("implementers may not spawn agents")


def check_manage(*, actor_role: Role, actor_team: str, target_team: str) -> None:
    if actor_role == "main":
        return
    if actor_role == "team" and target_team == actor_team:
        return
    raise PermissionError_("you may only manage agents in your own team")


def build_server() -> FastMCP:
    from groktimizer.core.blaxel_client import BlaxelSandboxClient
    import runpod as rp

    cfg = Config.model_validate_json(os.environ["GTZ_CONFIG_JSON"])
    role: Role = os.environ["GTZ_ROLE"]  # type: ignore[assignment]
    my_team = os.environ["GTZ_TEAM"]
    rp.api_key = os.environ["RUNPOD_API_KEY"]

    client = BlaxelSandboxClient(cfg.region)
    registry = Registry(client, cfg.project)
    gpus = BudgetedRunPod(rp, cfg.budget, Path("/var/lib/gtz/ledger.json"))
    mcp = FastMCP("groktimizer")

    def _team_of(sandbox: str) -> str:
        # gtz-{project}-{team}-{agent}
        return sandbox.removeprefix(f"gtz-{cfg.project}-").split("-")[0]

    @mcp.tool()
    async def list_teams() -> list[str]:
        """List all team names in this project."""
        return await registry.list_teams()

    @mcp.tool()
    async def list_agents(team: str | None = None) -> list[dict]:
        """List agents (optionally within one team) with role and sandbox name."""
        return [vars(a) for a in await registry.list_agents(team)]

    @mcp.tool(name="spawn_agent")
    async def spawn_agent_tool(team: str, agent: str, role_: str, brief: str) -> str:
        """Spawn a subordinate agent. role_ is 'team' or 'implementer'. Spawning a
        'team' role into a new team name creates that team (main orchestrator only)."""
        check_spawn(actor_role=role, actor_team=my_team,
                    target_role=role_, target_team=team)  # type: ignore[arg-type]
        await registry.ensure_can_spawn(role_, team, cfg.caps)  # type: ignore[arg-type]
        envs = {k: v for k in PASSTHROUGH_ENVS if (v := os.environ.get(k))}
        return await spawn_agent(cfg, client, team=team, agent=agent,
                                 role=role_, brief=brief, extra_envs=envs)  # type: ignore[arg-type]

    @mcp.tool()
    async def agent_status(sandbox: str) -> dict:
        """Check whether a subordinate's grok session is alive and when it last logged."""
        check_manage(actor_role=role, actor_team=my_team, target_team=_team_of(sandbox))
        return await monitor.agent_status(client, sandbox)

    @mcp.tool()
    async def tail_agent(sandbox: str, lines: int = 50) -> str:
        """Read the last N lines of a subordinate's session log."""
        check_manage(actor_role=role, actor_team=my_team, target_team=_team_of(sandbox))
        return await monitor.tail_log(client, sandbox, lines)

    @mcp.tool()
    async def exec_in_agent(sandbox: str, command: str) -> str:
        """Run a shell command inside a subordinate's sandbox."""
        check_manage(actor_role=role, actor_team=my_team, target_team=_team_of(sandbox))
        return await monitor.exec_in_agent(client, sandbox, command)

    @mcp.tool()
    async def send_to_agent(sandbox: str, message: str) -> str:
        """Send a steering message to a subordinate (resumes its grok session)."""
        check_manage(actor_role=role, actor_team=my_team, target_team=_team_of(sandbox))
        await monitor.send_message(client, sandbox, message)
        return "sent"

    @mcp.tool()
    async def terminate_agent(sandbox: str) -> str:
        """Delete a subordinate's sandbox."""
        check_manage(actor_role=role, actor_team=my_team, target_team=_team_of(sandbox))
        await client.delete(sandbox)
        return "terminated"

    @mcp.tool()
    def provision_gpu(name: str, image: str, gpu_type: str) -> dict:
        """Provision a RunPod GPU pod (budget-enforced). Terminate it when done."""
        return gpus.provision(name, image, gpu_type)

    @mcp.tool()
    def list_pods() -> dict:
        """List live pods, current spend, and reap over-lifetime pods."""
        reaped = gpus.reap_expired()
        return {"live": gpus.ledger["live"], "spend_usd": gpus.current_spend_usd(),
                "reaped": reaped, "ceiling_usd": cfg.budget.spend_ceiling_usd}

    @mcp.tool()
    def terminate_pod(pod_id: str) -> str:
        """Terminate a RunPod pod and record its cost."""
        gpus.terminate(pod_id)
        return "terminated"

    return mcp
```

```python
# groktimizer/mcp/__main__.py
"""Entry point: `python -m groktimizer.mcp` (registered with grok at bootstrap)."""
from groktimizer.mcp.server import build_server

build_server().run()  # stdio transport
```

Note: `run_on_gpu` from the spec is covered by `provision_gpu` + grok's own shell access to
`ssh`/`runpodctl` on the pod; implementers exec onto pods directly. Do not add a separate tool.
(Deviation from spec tool list, agreed rationale: YAGNI — revisit after smoke test.)

- [ ] **Step 4: Run** `uv run pytest tests/test_mcp_gating.py -v` — Expected: PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: role-gated MCP server"`

---

### Task 10: Blaxel adapter (`groktimizer/core/blaxel_client.py`)

**Files:** Create `groktimizer/core/blaxel_client.py`

This is the only module that imports the Blaxel SDK. No unit tests (covered by the e2e
smoke); keep it thin. **Verify the exact SDK call shapes with context7
(`/blaxel-ai/docs`: sandbox get/list/delete, process exec and output retrieval) while
implementing — the `create`/`fs.write` shapes below are confirmed, `list/get/delete/exec`
shapes are best-effort and may need adjustment.**

- [ ] **Step 1: Implement**

```python
# groktimizer/core/blaxel_client.py
"""The one module that touches the Blaxel SDK. Everything else uses SandboxClient."""
from blaxel.core import SandboxInstance

from groktimizer.core.sandbox import ExecResult, SandboxMeta


class BlaxelSandboxClient:
    def __init__(self, region: str):
        self.region = region

    async def create(self, name, image, region, labels, envs):
        await SandboxInstance.create_if_not_exists({
            "name": name,
            "image": image,
            "memory": 4096,
            "region": region or self.region,
            "labels": labels,
            "envs": [{"name": k, "value": v} for k, v in envs.items()],
        })

    async def delete(self, name):
        await SandboxInstance.delete(name)

    async def list(self, labels):
        out = []
        for sb in await SandboxInstance.list():
            sb_labels = dict(getattr(sb.metadata, "labels", {}) or {})
            if all(sb_labels.get(k) == v for k, v in labels.items()):
                out.append(SandboxMeta(name=sb.metadata.name, labels=sb_labels))
        return out

    async def exec(self, name, command, timeout_s=120):
        sb = await SandboxInstance.get(name)
        proc = await sb.process.exec({
            "command": command,
            "wait_for_completion": True,
            "timeout": timeout_s * 1000,
        })
        logs = await sb.process.logs(proc.pid)
        return ExecResult(stdout=logs, exit_code=proc.exit_code or 0)

    async def write_file(self, name, path, content):
        sb = await SandboxInstance.get(name)
        await sb.fs.write(path, content)
```

- [ ] **Step 2: Sanity check** `uv run python -c "import groktimizer.core.blaxel_client"` — Expected: no error
- [ ] **Step 3: Run full suite** `uv run pytest -v` — Expected: all PASS
- [ ] **Step 4: Commit** `git add -A && git commit -m "feat: Blaxel SDK adapter"`

---

### Task 11: CLI (`groktimizer/cli/main.py`)

**Files:** Create `groktimizer/cli/main.py`, `tests/test_cli.py`

- [ ] **Step 1: Write failing test (tree formatting only; commands are thin wrappers)**

```python
# tests/test_cli.py
from groktimizer.cli.main import format_tree
from groktimizer.core.registry import AgentInfo


def test_format_tree():
    agents = [
        AgentInfo("demo", "hq", "main", "main", "gtz-demo-hq-main"),
        AgentInfo("demo", "attn", "lead", "team", "gtz-demo-attn-lead"),
        AgentInfo("demo", "attn", "impl-1", "implementer", "gtz-demo-attn-impl-1"),
    ]
    out = format_tree(agents)
    assert out.index("main") < out.index("attn") < out.index("impl-1")
```

- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py -v` — Expected: FAIL

- [ ] **Step 3: Implement**

```python
# groktimizer/cli/main.py
"""gtz — human operator CLI. Thin wrappers over core; config from ./groktimizer.toml."""
import asyncio
import os
from pathlib import Path

import typer

from groktimizer.config import Config, load_config
from groktimizer.core import monitor
from groktimizer.core.bootstrap import PASSTHROUGH_ENVS, spawn_agent
from groktimizer.core.gpu import BudgetedRunPod
from groktimizer.core.registry import AgentInfo, Registry
from groktimizer.core.sandbox import MAIN_TEAM

app = typer.Typer(no_args_is_help=True)


def _cfg() -> Config:
    return load_config(Path("groktimizer.toml"))


def _client(cfg: Config):
    from groktimizer.core.blaxel_client import BlaxelSandboxClient
    return BlaxelSandboxClient(cfg.region)


def format_tree(agents: list[AgentInfo]) -> str:
    lines = []
    for a in sorted(agents, key=lambda a: (a.team != MAIN_TEAM, a.team, a.role != "team", a.agent)):
        indent = "" if a.team == MAIN_TEAM else ("  " if a.role == "team" else "    ")
        label = a.team if a.role == "team" else a.agent
        lines.append(f"{indent}{label} [{a.role}] ({a.sandbox_name})")
    return "\n".join(lines)


@app.command()
def start(brief: str):
    """Spawn the main orchestrator with a research brief."""
    cfg = _cfg()
    envs = {k: v for k in PASSTHROUGH_ENVS if (v := os.environ.get(k))}
    name = asyncio.run(spawn_agent(cfg, _client(cfg), team=MAIN_TEAM, agent="main",
                                   role="main", brief=brief, extra_envs=envs))
    typer.echo(f"main orchestrator started: {name}")


@app.command()
def tree():
    """Show all teams and agents."""
    cfg = _cfg()
    agents = asyncio.run(Registry(_client(cfg), cfg.project).list_agents())
    typer.echo(format_tree(agents) or "(no agents)")


@app.command()
def tail(sandbox: str, lines: int = 50):
    """Tail an agent's session log."""
    cfg = _cfg()
    typer.echo(asyncio.run(monitor.tail_log(_client(cfg), sandbox, lines)))


@app.command()
def send(sandbox: str, message: str):
    """Send a steering message to an agent."""
    cfg = _cfg()
    asyncio.run(monitor.send_message(_client(cfg), sandbox, message))
    typer.echo("sent")


@app.command()
def spend():
    """Show GPU spend (local ledger mirror; authoritative ledger lives with the agents)."""
    import runpod as rp
    cfg = _cfg()
    rp.api_key = os.environ["RUNPOD_API_KEY"]
    gpus = BudgetedRunPod(rp, cfg.budget, Path(".gtz/ledger.json"))
    typer.echo(f"live pods: {list(gpus.ledger['live'])}")
    typer.echo(f"spend: ${gpus.current_spend_usd():.2f} / ${cfg.budget.spend_ceiling_usd:.2f}")


@app.command()
def stop():
    """Tear down every sandbox in the project."""
    cfg = _cfg()
    client = _client(cfg)

    async def _stop():
        agents = await Registry(client, cfg.project).list_agents()
        for a in agents:
            await client.delete(a.sandbox_name)
        return len(agents)

    typer.echo(f"deleted {asyncio.run(_stop())} sandboxes")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run** `uv run pytest -v` — Expected: all PASS; also `uv run gtz --help` shows commands
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: gtz CLI"`

---

### Task 12: Smoke e2e script + README

**Files:** Create `scripts/smoke_e2e.md` (runbook), `README.md`

The e2e is a human-supervised runbook, not CI: it costs real money and needs real keys.

- [ ] **Step 1: Write `scripts/smoke_e2e.md`**

```markdown
# Smoke test runbook (real Blaxel + RunPod + grok; ~$1)

Prereqs: `BL_API_KEY`, `BL_WORKSPACE`, `RUNPOD_API_KEY`, `XAI_API_KEY` exported;
`groktimizer.toml` present with a tiny budget (ceiling $2, 1 pod, RTX 4090) and
`max_teams=1`, `max_agents_per_team=1`; shared repo exists and the deploy key works;
this repo pushed so `tooling_repo` is pip-installable.

1. `uv run gtz start "Optimize a softmax CUDA kernel for a 4096x4096 fp16 input. One team, one implementer. Target: beat torch.softmax latency."`
2. `uv run gtz tree` — within ~10 min expect main + 1 team orchestrator + 1 implementer.
3. `uv run gtz tail gtz-<project>-hq-main` — orchestrator reasoning visible.
4. Watch the shared repo for an `agent/*` branch with a benchmark JSON.
5. `uv run gtz send gtz-<project>-hq-main "Status report please"` → visible in tail.
6. `uv run gtz spend` — ledger under ceiling; RunPod console shows no orphan pods.
7. `uv run gtz stop` — `gtz tree` empty; Blaxel console shows no gtz-* sandboxes.

Known verification points (fix forward if they fail):
- grok non-interactive auth via XAI_API_KEY (docs.x.ai/build/cli)
- `grok mcp add` syntax in bootstrap SETUP_SH
- Blaxel SDK list/get/delete/exec call shapes in blaxel_client.py
```

- [ ] **Step 2: Write `README.md`** — short: what it is (3-layer grok hierarchy diagram in text), install (`uv sync`), configure (`cp groktimizer.toml.example groktimizer.toml`, env vars), usage (`gtz start/tree/tail/send/spend/stop`), links to spec and this plan.

- [ ] **Step 3: Run** `uv run pytest -v` — Expected: all PASS
- [ ] **Step 4: Commit** `git add -A && git commit -m "docs: README and smoke-test runbook"`
```
