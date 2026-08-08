"""Provision a new agent: sandbox, grok CLI, MCP registration, kickoff session."""
import shlex

from groktimizer.config import Config
from groktimizer.core.sandbox import (Role, SandboxClient, agent_labels, sandbox_name,
                                      validate_name)
from groktimizer.prompts import render_brief

# Live-verified 2026-08-08 against blaxel/py-app:latest (Debian 13) + grok 1.0.0:
# apt/curl/tmux install path, `grok mcp add NAME -- CMD ARGS`, `-p <PROMPT>` (the
# prompt is -p's argument), XAI_API_KEY-only headless auth, and --continue resuming
# the latest session for the working directory (so kickoff and steering both run
# from /workspace/project).
#
# Secrets are NOT passed as sandbox create-time envs (visible to the control plane);
# they are written to /opt/gtz/.env (chmod 600) and sourced with xtrace disabled so
# `set -x` can't echo them into exec output or the session log.
SETUP_SH = """#!/usr/bin/env bash
set -euo pipefail
{ set +x; } 2>/dev/null
[ -f /opt/gtz/.env ] && . /opt/gtz/.env
set -x
export DEBIAN_FRONTEND=noninteractive
export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"
apt-get update -qq >/dev/null
apt-get install -y -qq curl tmux >/dev/null
curl -fsSL https://x.ai/cli/install.sh | bash
pip install --quiet "git+${GTZ_TOOLING_REPO}"
[ -d /workspace/project/.git ] || git clone "${GTZ_SHARED_REPO}" /workspace/project
grok mcp add groktimizer -- python3 -m groktimizer.mcp
mkdir -p /var/log/gtz
tmux new-session -d -s gtz \\
  '{ . /opt/gtz/.env; } 2>/dev/null; export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; \\
   cd /workspace/project; \\
   grok --always-approve ${GTZ_GROK_MODEL:+--model "$GTZ_GROK_MODEL"} \\
   -p "$(cat /opt/gtz/brief.md)" 2>&1 | tee -a /var/log/gtz/session.log'
"""

PASSTHROUGH_ENVS = ("RUNPOD_API_KEY", "XAI_API_KEY", "BL_API_KEY", "BL_WORKSPACE")


def render_env_file(secrets: dict[str, str]) -> str:
    return "".join(f"export {k}={shlex.quote(v)}\n" for k, v in secrets.items())


async def spawn_agent(cfg: Config, client: SandboxClient, *, team: str, agent: str,
                      role: Role, brief: str, extra_envs: dict[str, str] | None = None) -> str:
    validate_name("project", cfg.project)
    validate_name("team", team)
    validate_name("agent", agent)
    name = sandbox_name(cfg.project, team, agent)
    envs = {
        "GTZ_PROJECT": cfg.project,
        "GTZ_TEAM": team,
        "GTZ_AGENT": agent,
        "GTZ_ROLE": role,
        "GTZ_SHARED_REPO": cfg.shared_repo,
        "GTZ_TOOLING_REPO": cfg.tooling_repo,
        "GTZ_CONFIG_JSON": cfg.model_dump_json(),
    }
    if role == "reconciler" and cfg.research.reconciler_model:
        envs["GTZ_GROK_MODEL"] = cfg.research.reconciler_model
    await client.create(name, cfg.image, cfg.region,
                        labels=agent_labels(cfg.project, team, agent, role), envs=envs)
    rendered = render_brief(role, cfg, team=team, agent=agent, brief=brief)
    await client.exec(name, "mkdir -p /opt/gtz")
    await client.write_file(name, "/opt/gtz/brief.md", rendered)
    await client.write_file(name, "/opt/gtz/.env", render_env_file(extra_envs or {}))
    await client.exec(name, "chmod 600 /opt/gtz/.env")
    await client.write_file(name, "/opt/gtz/setup.sh", SETUP_SH)
    await client.exec(name, "bash /opt/gtz/setup.sh", timeout_s=900)
    return name
