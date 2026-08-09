# Production smoke-test runbook (Blaxel + RunPod + Grok)

## Already verified live (2026-08-08)

- Sandbox create with `gtz-*` labels and envs; envs visible to exec'd processes.
- Registry: `list_agents`/`list_teams` by label, team/implementer caps, project isolation.
- Exec: stdout + stderr capture, exit codes, 3s+ commands, `write_file` round-trip.
- Monitor: `agent_status` (tmux + log mtime), `tail_log`, `exec_in_agent`.
- CLI against real Blaxel: `gtz tree`, `gtz tail`, `gtz stop`.
- Deletion is eventually consistent (sandboxes linger in listings for a few seconds).
- Image: `blaxel/py-app:latest` (Debian 13, root, python3/pip/git/apt; pip NOT
  PEP668-managed). `blaxel/base-image:latest` is Alpine — do not use.
- Full SETUP_SH sequence minus grok auth: apt install curl+tmux, grok CLI install
  (`grok 1.0.0` at `~/.grok/bin/grok`), pip git-install, tmux session with log tee.
- grok 1.0.0 flags: `-p/--single <PROMPT>` (prompt is the argument), `--always-approve`,
  `-c/--continue` (per-working-directory), `grok mcp add NAME -- CMD ARGS`,
  `--output-format` for headless. No `--session-id`, no `--no-auto-update`.

## Also verified live (2026-08-08, with real XAI_API_KEY)

- **grok headless auth**: `XAI_API_KEY` env alone is enough — `grok --always-approve -p
  "Reply with exactly: AUTH-OK"` returned `AUTH-OK`, no OAuth screen.
- **Models**: `grok models` lists grok-4.5 (500k ctx, most capable), grok-4.3 (1M ctx),
  grok-4.20 variants (1M), and grok-build-0.1 (256k). All autoresearch roles are pinned
  to grok-4.5 with high reasoning; `-m/--model` works.
- **MCP integration end-to-end**: groktimizer sdist installed in the sandbox,
  `grok mcp add groktimizer -- python3 -m groktimizer.mcp` → `grok mcp doctor` reports
  handshake OK, 12 tools discovered; a headless grok run called `list_agents` and got the
  live Blaxel registry back.
- **Kickoff + steering**: the queued runner executed a task and logged diagnostics to
  /var/log/gtz/runner.log; `monitor.send_message` (the same exact Grok session from
  /workspace/project) resumed the same session and executed the follow-up instruction.

## Also verified live (2026-08-08, with real RUNPOD_API_KEY)

- Full BudgetedRunPod cycle: `get_gpu` pricing, RTX PRO 6000 allowlist enforcement,
  provision (pod created and visible via `get_pods`), ledger live-entry + spend accrual,
  concurrency-cap denial, terminate (pod gone from API, cost settled into the ledger).
- Availability note: `cloud_type="COMMUNITY"` returned "machine does not have the
  resources"; the SDK default `"ALL"` (what the MCP tool uses) provisioned fine.

## Fresh-environment verification

1. `uv run gtz start "Optimize a softmax CUDA kernel for 4096x4096 fp16. One team, one implementer. Target: beat torch.softmax latency."`
2. `uv run gtz tree` — within ~10 min expect main + 1 team orchestrator + 1 implementer.
3. `uv run gtz tail gtz-<project>-hq-main` — orchestrator reasoning visible; confirm the
   groktimizer MCP tools appear in its tool calls (`grok mcp list` in the sandbox).
4. Watch the shared repo for an `agent/*` branch with a benchmark JSON.
5. `uv run gtz send gtz-<project>-hq-main "Status report please"` → visible in tail
   (send uses `--continue` from /workspace/project).
6. `uv run gtz spend` — ledger under ceiling; RunPod console shows no orphan pods.
7. `uv run gtz stop` — `gtz tree` empty (allow a few seconds for deletion propagation);
   Blaxel console shows no `gtz-*` sandboxes.
