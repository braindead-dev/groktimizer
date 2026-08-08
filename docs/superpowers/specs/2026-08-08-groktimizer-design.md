# Groktimizer Design

**Date:** 2026-08-08
**Status:** Approved

## Purpose

An autoresearch system for GPU inference/kernel optimization. A three-layer hierarchy of
grok-build agents — 1 main orchestrator per project, up to 10 team orchestrators, up to 5
implementation agents per team — each running headless in its own Blaxel micro-VM sandbox,
collaborating through a shared git repo, and provisioning RunPod GPUs through budget-capped tools.

## Decisions (user-validated)

- Sandbox platform: **Blaxel** (blaxel.ai) — one sandbox per agent.
- Research goal: **inference/kernel optimization** (quantization, kernels, throughput/latency).
- All three layers are grok-build agents; we build the tooling (MCP tools + CLI) they use.
- Stack: **Python**.
- Work products flow through a **shared git repo**: implementer branches → team branches → main.
- **Enforced RunPod budget caps**: spend ceiling, max concurrent pods, GPU class allowlist,
  idle auto-terminate.
- Human interface: **CLI** (`gtz`).
- Architecture: **Blaxel-as-registry + MCP toolbelt** — no central service or database; the
  registry is Blaxel sandbox naming + labels. One Python package containing MCP server + CLI.
- Monitoring channel: **Blaxel sandbox exec** (Blaxel has no raw SSH; exec gives equivalent
  capability — run commands, read logs inside a subordinate's sandbox).

## Architecture

One Python package `groktimizer`:

- `core/` — Blaxel sandbox lifecycle (naming `gtz-{project}-{team}-{agent}`, labels for
  role/team/project), registry-by-labels, agent bootstrap (install grok CLI, write grok config
  registering our MCP server, start `grok -p --always-approve` under tmux with a known log path),
  monitoring (status/tail/exec/send via sandbox exec; send = resume the subordinate's grok
  session with a new prompt), and a budget-enforcing RunPod wrapper with a JSON spend ledger.
- `mcp/` — stdio MCP server every agent gets, tools role-gated by the agent's own role:
  - `spawn_agent(team, role, brief)` — main: any; team orchestrator: own implementers only;
    implementer: denied. Spawning into a new team name creates the team (main only).
  - `list_teams` / `list_agents` — all roles.
  - `agent_status` / `tail_agent` / `exec_in_agent` / `send_to_agent` / `terminate_agent` —
    orchestrators, own subordinates only.
  - `provision_gpu` / `run_on_gpu` / `list_pods` / `terminate_pod` — all roles, budget-wrapped.
  - Web search comes from grok-build's built-in tools.
- `cli/` — `gtz start|tree|tail|send|spend|stop` for the human operator, reusing `core/`.
- `prompts/` — role system prompts (main orchestrator, team orchestrator, implementer).

## Constraints & error handling

- Caps (≤10 teams, ≤5 implementers/team; configurable) checked at spawn time against live
  Blaxel state — no drift possible.
- Budget refusals are readable tool errors agents can escalate up the hierarchy.
- Stall detection: orchestrators poll `agent_status` (session log age + process check),
  terminate and respawn dead agents.
- Durability: work products in git, ledger on a Blaxel volume; a dead sandbox loses only
  in-flight work.

## Testing

- Unit tests with mocked Blaxel/RunPod SDKs: caps, budget enforcement, role gating, naming.
- `scripts/smoke_e2e.py`: real 1-team/1-implementer run with a toy kernel task and a small
  spend cap; verifies spawn → work → report → merge → teardown.

## External facts (verified 2026-08-08)

- grok-build headless: `grok -p`, `--session-id/--resume/--continue` (sessions in
  `~/.grok/sessions`), `--always-approve`, `--no-auto-update`, `--output-format`.
  Install: `curl -fsSL https://x.ai/cli/install.sh | bash`. Docs: https://docs.x.ai/build/cli/headless-scripting
- Blaxel: named sandboxes + labels, Python SDK, REST process/filesystem API,
  `bl connect sandbox <name>`, volumes, scale-to-zero/resume. Docs: https://docs.blaxel.ai/Sandboxes/Overview
