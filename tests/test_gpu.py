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


def test_terminate_settles_ledger_when_pod_already_gone(rp, tmp_path):
    b = mk(rp, tmp_path)
    pod = b.provision("bench", "img", GPU)
    rp.terminate_pod(pod["id"])  # pod dies out-of-band
    b.terminate(pod["id"])  # must not raise, and must settle the ledger
    assert b.ledger["live"] == {}
    assert b.current_spend_usd() >= 0


def test_ceiling_accounts_for_live_pods_full_lifetime(rp, tmp_path):
    # 0.60/hr * 2h = 1.20 per pod; ceiling 2.0 fits one pod's worst case, not two
    b = mk(rp, tmp_path, spend_ceiling_usd=2.0, max_pod_lifetime_hours=2.0,
           max_concurrent_pods=5)
    b.provision("a", "img", GPU)
    with pytest.raises(BudgetError, match="ceiling"):
        b.provision("b", "img", GPU)
