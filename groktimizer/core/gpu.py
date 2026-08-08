# groktimizer/core/gpu.py
"""RunPod wrapper enforcing project GPU budget: allowlist, concurrency, spend ceiling, lifetime."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from groktimizer.config import Budget

logger = logging.getLogger(__name__)


class BudgetError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


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
        tmp = self.ledger_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.ledger, indent=2))
        tmp.replace(self.ledger_path)  # atomic: a crash mid-write can't corrupt the ledger

    def _rate(self, gpu_type: str) -> float:
        gpu = self.rp.get_gpu(gpu_type)
        return float(gpu["lowestPrice"]["uninterruptablePrice"])

    def _age_hours(self, entry: dict) -> float:
        return (_now() - datetime.fromisoformat(entry["started_at"])).total_seconds() / 3600

    def _accrued(self, entry: dict) -> float:
        return self._age_hours(entry) * entry["cost_per_hr"]

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
        limit = self.budget.max_pod_lifetime_hours
        # Project every live pod (and the new one) to its full lifetime so concurrent
        # pods can't jointly overshoot the ceiling.
        live_worst = sum(e["cost_per_hr"] * limit for e in self.ledger["live"].values())
        projected = self.ledger["completed_usd"] + live_worst + rate * limit
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
        try:
            self.rp.terminate_pod(pod_id)
        except Exception:  # noqa: BLE001 -- RunPod exposes inconsistent SDK exception types.
            # The pod may already be gone on RunPod's side; settle the ledger anyway
            # so a dead entry can't accrue cost forever and eat the ceiling.
            logger.warning("RunPod could not terminate pod %s; settling its ledger entry", pod_id)
        entry = self.ledger["live"].pop(pod_id, None)
        if entry:
            self.ledger["completed_usd"] += self._accrued(entry)
        self.save()

    def reap_expired(self) -> list[str]:
        limit = self.budget.max_pod_lifetime_hours
        expired = [pid for pid, e in self.ledger["live"].items() if self._age_hours(e) > limit]
        for pid in expired:
            self.terminate(pid)
        return expired
