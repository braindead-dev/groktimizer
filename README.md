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

There is no central service: the registry **is** Blaxel — every agent is a sandbox named
`gtz-{project}-{team}-{agent}` with `gtz-*` labels, and caps are enforced against live state
at spawn time. Orchestrators monitor and steer subordinates over the sandbox exec channel
(read session logs, run commands, resume the subordinate's grok session with a message).
All of that is exposed to the agents as role-gated MCP tools served by
`python3 -m groktimizer.mcp` inside each sandbox.

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
uv run gtz tail <sandbox-name>      # an agent's live session log
uv run gtz watch <sandbox-name>     # stream status + log snapshots as JSONL
uv run gtz send <sandbox-name> "Status report please"
uv run gtz spend                    # GPU ledger vs ceiling
uv run gtz stop                     # delete every sandbox in the project
```

### Add the optimized deployment to Grok Build

Install stock [Grok Build](https://github.com/xai-org/grok-build) normally, then add the live
optimized model globally with one command:

```bash
curl -fsSL https://raw.githubusercontent.com/braindead-dev/groktimizer/main/install.sh | sh
```

The installer probes the endpoint, backs up and safely updates `~/.grok/config.toml`, registers the
model everywhere stock Grok Build discovers models, and selects `Groktimized 2` for new sessions.
Afterward, launch normally with `grok`, switch with `/model Groktimized 2`, or use
`grok -m groktimized-2`. Re-running the installer updates the managed entry without duplicating it.

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

## Layout

- `groktimizer/core/` — Blaxel adapter (`blaxel_client.py`, the only module touching the SDK),
  label-based registry with cap enforcement, agent bootstrap, monitoring, budget-enforcing
  RunPod wrapper (`gpu.py`).
- `groktimizer/mcp/` — role-gated MCP server each agent runs.
- `groktimizer/cli/` — the `gtz` operator CLI.
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

## Status (2026-08-08)

The control plane and authenticated multi-agent loop are live-verified against real Blaxel
sandboxes, including creation, labels, permission-hardened environment files, registry caps,
branch publication, monitoring, steering, and teardown. RunPod access is wired behind the spend,
GPU-type, concurrency, and lifetime gates; the current project intentionally avoided provisioning
hardware that violated those constraints. See `scripts/smoke_e2e.md` for the operator runbook.
