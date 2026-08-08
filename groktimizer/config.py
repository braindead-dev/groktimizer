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


class Research(BaseModel):
    target_gain_pct: float = 5.0        # min perf gain orchestrators should accept
    max_accuracy_loss_pct: float = 5.0  # max model-quality regression tolerated
    benchmark_cmd: str = "python3 bench/benchmark.py"  # run in shared repo; prints metrics JSON
    accuracy_cmd: str = "python3 bench/accuracy.py"    # run in shared repo; prints accuracy metric
    # Final reconciler runs on the largest-context model so it can hold every team's
    # reports/branches at once. Live-checked 2026-08-08: grok-4.3 = newest 1M-token
    # model (grok-4.5 is smarter but only 500k). "" = grok CLI default.
    reconciler_model: str = "grok-4.3"


class Config(BaseModel):
    project: str
    shared_repo: str
    tooling_repo: str
    image: str = "blaxel/py-app:latest"
    region: str = "us-pdx-1"
    caps: Caps = Caps()
    budget: Budget = Budget()
    research: Research = Research()


def load_config(path: Path) -> Config:
    data = tomllib.loads(path.read_text())
    flat = {
        **data.get("project", {}),
        "caps": data.get("caps", {}),
        "budget": data.get("budget", {}),
        "research": data.get("research", {}),
    }
    # [project] name= maps to Config.project
    flat["project"] = flat.pop("name")
    return Config.model_validate(flat)
