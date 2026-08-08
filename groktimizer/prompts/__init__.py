"""Role prompt templates rendered into each agent's kickoff brief."""

from importlib import resources

from groktimizer.config import Config

_FILES = {
    "main": "main_orchestrator.md",
    "team": "team_orchestrator.md",
    "implementer": "implementer.md",
    "reconciler": "reconciler.md",
}


def render_brief(role: str, cfg: Config, *, team: str, agent: str, brief: str) -> str:
    template = (resources.files("groktimizer.prompts") / _FILES[role]).read_text()
    fields = {
        "project": cfg.project,
        "team": team,
        "agent": agent,
        "shared_repo": cfg.shared_repo,
        "max_teams": str(cfg.caps.max_teams),
        "max_agents_per_team": str(cfg.caps.max_agents_per_team),
        "target_gain_pct": f"{cfg.research.target_gain_pct:g}",
        "max_accuracy_loss_pct": f"{cfg.research.max_accuracy_loss_pct:g}",
        "benchmark_cmd": cfg.research.benchmark_cmd,
        "accuracy_cmd": cfg.research.accuracy_cmd,
        "brief": brief,
    }
    text = template
    # Plain replace (not str.format) so braces in the brief or commands can't
    # crash rendering. Each replace() scans the current text, so {brief} is
    # substituted last and placeholder-like strings inside it are left alone.
    brief_value = fields.pop("brief")
    for key, value in fields.items():
        text = text.replace("{" + key + "}", value)
    return text.replace("{brief}", brief_value)
