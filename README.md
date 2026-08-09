# Groktimizer

An autoresearch system for GPU inference/kernel optimization: a three-layer hierarchy of
[grok-build](https://github.com/xai-org/grok-build) agents, each running headless in its own
[Blaxel](https://blaxel.ai) micro-VM sandbox, provisioning RunPod GPUs through budget-capped
tools and collaborating through a shared git repo.

```
main orchestrator (1, team "hq")
├── team orchestrator (≤3 teams)
│   ├── implementer (≤5 per team)
│   └── implementer
└── team orchestrator
    └── implementer
```

Blaxel remains the live agent registry: every agent is a sandbox named
`gtz-{project}-{team}-{agent}` with `gtz-*` labels, and caps are enforced against live state at
spawn time. The operator control plane durably mirrors projects, ordered turns, events, and runtime
cursors into SQLite. It is available through the `gtz` CLI and the authenticated `gtz-api` HTTP
service. Orchestrators monitor and steer subordinates over the sandbox exec channel; role-gated MCP
tools are served by `python3 -m groktimizer.mcp` inside each sandbox.

## Install

```bash
uv sync
cp groktimizer.toml.example groktimizer.toml   # then edit
export BL_API_KEY=... BL_WORKSPACE=...          # Blaxel
export RUNPOD_API_KEY=...                       # RunPod (GPU budget tools)
export XAI_API_KEY=...                          # grok auth inside sandboxes
export XAI_API_KEY_2=...                        # optional second quota pool key
export GITHUB_TOKEN=...                         # fine-grained Contents read/write for agent branches
```

## Usage

```bash
uv run gtz start "Optimize softmax kernels for fp16 4096x4096; beat torch.softmax."
uv run gtz tree                     # teams and agents
uv run gtz snapshot                 # machine-readable live control-plane state
uv run gtz tail <sandbox-name>      # an agent runner's diagnostic log
uv run gtz watch <sandbox-name>     # stream status + log snapshots as JSONL
uv run gtz send <sandbox-name> "Status report please"
uv run gtz spend                    # GPU ledger vs ceiling
uv run gtz stop                     # delete every sandbox in the project
```

### Add the optimized deployment to Grok Build

Install stock [Grok Build](https://github.com/xai-org/grok-build) normally, then add the live
optimized model globally with one command:

```bash
curl -fsSL https://groktimizer.com/install.sh | sh
```

The installer probes the accelerated `grok-2-fast` deployment, backs up and safely updates
`~/.grok/config.toml`, registers the model everywhere Grok Build discovers models, and selects
`Groktimized 2` for new sessions. On
macOS Apple Silicon it also installs a checksummed, source-available patch of the stock Grok Build
1.0.0 binary: the model's actual text is purple in the selector, prompt chrome, dashboard, and
minimal mode, and it appears first in `/model`. The stock binary is left intact and its symlink
state is recorded for rollback.

Afterward, launch normally with `grok`, switch with `/model groktimized-2`, or use
`grok -m groktimized-2`. Re-running the installer is idempotent. Restore the stock binary links at
any time without removing the model configuration:

```bash
curl -fsSL https://groktimizer.com/install.sh | sh -s -- --restore-stock
```

### Web command center

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). With `groktimizer.toml` and credentials
configured at the repository root, the UI reads the live Blaxel registry, streams the selected
agent over SSE, and sends steering messages through `gtz send`. Without a live connection it
shows only the committed benchmark artifacts from `results/*.json`; synthetic agents are never
inserted into the project tree.

For production, run `gtz-api` on one persistent host and set these server-only variables on the
Next.js deployment:

```bash
GTZ_CONTROL_PLANE_URL=https://api.example.com
GTZ_CONTROL_PLANE_TOKEN=...
```

The browser receives neither the control-plane token nor provider credentials. Agent SSE streams
use short-lived, sandbox-scoped signed tickets and connect directly to the persistent API host.
The production Azure topology, Key Vault integration, managed data disk, and backup procedure are
documented in `deploy/azure/README.md`.

## Layout

- `groktimizer/core/` — Blaxel adapter (`blaxel_client.py`, the only module touching the SDK),
  label-based registry with cap enforcement, agent bootstrap, monitoring, budget-enforcing
  RunPod wrapper (`gpu.py`).
- `groktimizer/mcp/` — role-gated MCP server each agent runs.
- `groktimizer/cli/` — the `gtz` operator CLI.
- `groktimizer/api.py` — authenticated HTTP gateway, project recovery, and ticketed SSE.
- `groktimizer/prompts/` — role prompt templates.
- `frontend/` — Next.js command center, control-plane gateway, and SSE agent streams.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — design spec and implementation plan.
- `scripts/smoke_e2e.md` — real-infrastructure smoke-test runbook.

## Runtime contract

- Main, team, implementer, and reconciler agents are pinned to `grok-4.5` with high reasoning.
- A project can create at most three teams and five implementers per team.
- With two xAI keys, new sandboxes choose the least-used quota slot. Only orchestrators receive
  the private key pool needed to allocate keys to descendants.
- Branches are isolated as `main`, `team/<team>`, and `agent/<team>/<agent>` and are published
  during sandbox bootstrap.
- Steering messages are persisted in each sandbox. The web command center streams updates over
  SSE with heartbeats and never inserts synthetic agents or optimistic fake messages.

## Status (2026-08-09)

The control plane and authenticated multi-agent loop are live-verified against real Blaxel
sandboxes, including creation, labels, permission-hardened environment files, registry caps,
branch publication, monitoring, steering, and teardown. RunPod access is wired behind the spend,
GPU-type, concurrency, and lifetime gates; the current project intentionally avoided provisioning
hardware that violated those constraints. See `scripts/smoke_e2e.md` for the operator runbook.
The HTTP control plane is deployed on a supervised Azure VM with boot-time Key Vault retrieval,
TLS, a separate Premium SSD for SQLite, and geo-redundant Azure Backup.
