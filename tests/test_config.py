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
