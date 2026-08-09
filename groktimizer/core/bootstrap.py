"""Provision a new agent: sandbox, grok CLI, MCP registration, kickoff session."""

import hashlib
import json
import shlex
from pathlib import Path
from uuid import uuid4

from groktimizer.config import Config
from groktimizer.core.sandbox import (
    Role,
    SandboxClient,
    agent_labels,
    branch_name,
    sandbox_name,
    validate_name,
)
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
export GIT_ASKPASS=/opt/gtz/git-askpass.sh
export GIT_TERMINAL_PROMPT=0
cat >/opt/gtz/git-askpass.sh <<'GTZ_ASKPASS'
#!/usr/bin/env bash
case "$1" in
  *Username*) printf '%s\n' 'x-access-token' ;;
  *Password*) printf '%s\n' "${GITHUB_TOKEN:-${GH_TOKEN:-}}" ;;
esac
GTZ_ASKPASS
chmod 700 /opt/gtz/git-askpass.sh
git config --global user.name "Groktimizer"
git config --global user.email "groktimizer@users.noreply.github.com"
git config --global push.autoSetupRemote true
apt-get update -qq >/dev/null
apt-get install -y -qq curl tmux >/dev/null
curl -fsSL https://x.ai/cli/install.sh | bash
pip install --quiet "git+${GTZ_TOOLING_REPO}"
# A broken/missing shared repo degrades to a local-only workspace instead of
# killing the whole agent: the failure is loudly recorded for the operator and
# the agent itself, and the session (chat/steering) still comes up.
if [ ! -d /workspace/project/.git ]; then
  if ! git clone "${GTZ_SHARED_REPO}" /workspace/project; then
    mkdir -p /workspace/project
    cd /workspace/project
    git init -q -b main
    echo "shared repo unavailable at bootstrap: ${GTZ_SHARED_REPO}" > CLONE_FAILED.md
    git add CLONE_FAILED.md && git commit -qm "bootstrap: shared repo unavailable"
  fi
fi
cd /workspace/project
if git remote get-url origin >/dev/null 2>&1; then
  git fetch origin main
  if git ls-remote --exit-code --heads origin "$GTZ_BRANCH" >/dev/null 2>&1; then
    git fetch origin "$GTZ_BRANCH"
    git checkout -B "$GTZ_BRANCH" "origin/$GTZ_BRANCH"
  else
    git checkout -B "$GTZ_BRANCH" origin/main
  fi
  if [ "$GTZ_BRANCH" != "main" ]; then
    git push -u origin "$GTZ_BRANCH"
  fi
else
  git checkout -B "$GTZ_BRANCH"
fi
grok mcp add groktimizer -- python3 -m groktimizer.mcp
mkdir -p /var/log/gtz /var/lib/gtz
touch /var/log/gtz/runner.log
python3 /opt/gtz/agent_runner.py init --session-id "$GTZ_SESSION_ID"
python3 /opt/gtz/agent_runner.py enqueue \\
  --message-file /opt/gtz/brief.md \\
  --display-message-file /opt/gtz/objective.md \\
  --client-id "kickoff-$GTZ_SESSION_ID" \\
  --turn-id "turn-$GTZ_SESSION_ID" \\
  --sender-kind system \\
  --sender-label "Research brief"
tmux kill-session -t gtz 2>/dev/null || true
tmux new-session -d -s gtz \\
  '{ . /opt/gtz/.env; } 2>/dev/null; export PATH="$HOME/.local/bin:$HOME/.grok/bin:$PATH"; \\
   export GIT_ASKPASS=/opt/gtz/git-askpass.sh GIT_TERMINAL_PROMPT=0; \\
   cd /workspace/project; \\
   exec python3 /opt/gtz/agent_runner.py daemon >>/var/log/gtz/runner.log 2>&1'
"""

PASSTHROUGH_ENVS = (
    "RUNPOD_API_KEY",
    "XAI_API_KEY",
    "XAI_API_KEY_2",
    "GTZ_XAI_KEY_POOL",
    "BL_API_KEY",
    "BL_WORKSPACE",
    "GITHUB_TOKEN",
    "GH_TOKEN",
)


def render_env_file(secrets: dict[str, str]) -> str:
    return "".join(f"export {k}={shlex.quote(v)}\n" for k, v in secrets.items())


def xai_key_pool(secrets: dict[str, str]) -> list[str]:
    """Recover the private key pool passed by the root process or a spawning orchestrator."""
    pool: list[str] = []
    encoded_pool = secrets.get("GTZ_XAI_KEY_POOL")
    if encoded_pool:
        try:
            decoded = json.loads(encoded_pool)
            if isinstance(decoded, list):
                pool = [value for value in decoded if isinstance(value, str) and value]
        except json.JSONDecodeError:
            pool = []
    if not pool:
        pool = [value for key in ("XAI_API_KEY", "XAI_API_KEY_2") if (value := secrets.get(key))]
    return list(dict.fromkeys(pool))


def prepare_agent_secrets(
    secrets: dict[str, str], name: str, role: Role, slot: int | None = None
) -> dict[str, str]:
    """Choose one stable xAI credential while preserving the pool only for spawners."""
    prepared = {
        key: value
        for key, value in secrets.items()
        if key not in {"XAI_API_KEY", "XAI_API_KEY_2", "GTZ_XAI_KEY_POOL", "GTZ_XAI_KEY_SLOT"}
    }
    pool = xai_key_pool(secrets)
    if pool:
        if slot is None:
            slot = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") % len(pool)
        slot %= len(pool)
        prepared["XAI_API_KEY"] = pool[slot]
        prepared["GTZ_XAI_KEY_SLOT"] = str(slot + 1)
        if role in ("main", "team"):
            prepared["GTZ_XAI_KEY_POOL"] = json.dumps(pool, separators=(",", ":"))
    return prepared


async def spawn_agent(
    cfg: Config,
    client: SandboxClient,
    *,
    team: str,
    agent: str,
    role: Role,
    brief: str,
    extra_envs: dict[str, str] | None = None,
) -> str:
    validate_name("project", cfg.project)
    validate_name("team", team)
    validate_name("agent", agent)
    name = sandbox_name(cfg.project, team, agent)
    source_secrets = extra_envs or {}
    pool = xai_key_pool(source_secrets)
    slot: int | None = None
    labels = agent_labels(cfg.project, team, agent, role)
    if pool:
        existing = await client.list({"gtz-project": cfg.project})
        counts = [0] * len(pool)
        for sandbox in existing:
            raw_slot = sandbox.labels.get("gtz-xai-slot", "")
            if raw_slot.isdigit() and 1 <= int(raw_slot) <= len(pool):
                counts[int(raw_slot) - 1] += 1
        least_used = min(counts)
        candidates = [index for index, count in enumerate(counts) if count == least_used]
        tie_breaker = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big")
        slot = candidates[tie_breaker % len(candidates)]
        labels["gtz-xai-slot"] = str(slot + 1)
    envs = {
        "GTZ_PROJECT": cfg.project,
        "GTZ_TEAM": team,
        "GTZ_AGENT": agent,
        "GTZ_ROLE": role,
        "GTZ_SHARED_REPO": cfg.shared_repo,
        "GTZ_TOOLING_REPO": cfg.tooling_repo,
        "GTZ_CONFIG_JSON": cfg.model_dump_json(),
        "GTZ_BRANCH": branch_name(team, agent, role),
        "GTZ_SESSION_ID": str(uuid4()),
    }
    model = (
        cfg.research.reconciler_model
        if role == "reconciler"
        else cfg.research.implementer_model
        if role == "implementer"
        else cfg.research.orchestrator_model
    )
    if model:
        envs["GTZ_GROK_MODEL"] = model
    if cfg.research.reasoning_effort:
        envs["GTZ_REASONING_EFFORT"] = cfg.research.reasoning_effort
    await client.create(name, cfg.image, cfg.region, labels=labels, envs=envs)
    rendered = render_brief(role, cfg, team=team, agent=agent, brief=brief)
    await client.exec(name, "mkdir -p /opt/gtz")
    await client.write_file(name, "/opt/gtz/brief.md", rendered)
    await client.write_file(name, "/opt/gtz/objective.md", brief)
    runner_source = Path(__file__).with_name("agent_runner.py").read_text()
    await client.write_file(name, "/opt/gtz/agent_runner.py", runner_source)
    secrets = prepare_agent_secrets(source_secrets, name, role, slot=slot)
    await client.write_file(name, "/opt/gtz/.env", render_env_file(secrets))
    await client.exec(name, "chmod 600 /opt/gtz/.env")
    await client.write_file(name, "/opt/gtz/setup.sh", SETUP_SH)
    await client.exec(name, "bash /opt/gtz/setup.sh", timeout_s=900)
    return name
