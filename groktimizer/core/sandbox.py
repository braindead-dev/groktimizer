"""Sandbox naming, labels, and the client protocol all Blaxel access goes through."""

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["main", "team", "implementer", "reconciler"]
ROLES: tuple[str, ...] = ("main", "team", "implementer", "reconciler")
MAIN_TEAM = "hq"  # the main orchestrator's pseudo-team

# Hyphens are the sandbox-name separator, so project/team/agent names must not
# contain them — otherwise gtz-{project}-{team}-{agent} parses ambiguously and
# team-scoped permission checks can be bypassed (e.g. team "attn" vs "attn-opt").
_NAME_RE = re.compile(r"^[a-z0-9]{1,24}$")


class InvalidNameError(ValueError):
    pass


def validate_name(kind: str, value: str) -> str:
    if not _NAME_RE.fullmatch(value):
        raise InvalidNameError(
            f"invalid {kind} name {value!r}: must match [a-z0-9]{{1,24}} (no hyphens)"
        )
    return value


def sandbox_name(project: str, team: str, agent: str) -> str:
    return f"gtz-{project}-{team}-{agent}"


def branch_name(team: str, agent: str, role: Role) -> str:
    """Return the durable Git branch owned by one sandbox role."""
    if role in ("main", "reconciler"):
        return "main"
    if role == "team":
        return f"team/{team}"
    return f"agent/{team}/{agent}"


def agent_labels(project: str, team: str, agent: str, role: Role) -> dict[str, str]:
    return {
        "gtz-project": project,
        "gtz-team": team,
        "gtz-agent": agent,
        "gtz-role": role,
    }


@dataclass
class SandboxMeta:
    name: str
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ExecResult:
    stdout: str
    exit_code: int


class SandboxClient(Protocol):
    async def create(
        self,
        name: str,
        image: str,
        region: str,
        labels: dict[str, str],
        envs: dict[str, str],
    ) -> None: ...
    async def delete(self, name: str) -> None: ...
    async def list(self, labels: dict[str, str]) -> list[SandboxMeta]: ...
    async def exec(self, name: str, command: str, timeout_s: int = 120) -> ExecResult: ...
    async def write_file(self, name: str, path: str, content: str) -> None: ...
