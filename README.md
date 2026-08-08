# Groktimizer

An autoresearch system for GPU inference/kernel optimization: a three-layer hierarchy of
[grok-build](https://github.com/xai-org/grok-build) agents, each running headless in its own
[Blaxel](https://blaxel.ai) micro-VM sandbox, provisioning RunPod GPUs through budget-capped
tools and collaborating through a shared git repo.

```
main orchestrator (1, team "hq")
├── team orchestrator (≤10 teams)
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
```

## Usage

```bash
uv run gtz start "Optimize softmax kernels for fp16 4096x4096; beat torch.softmax."
uv run gtz tree                     # teams and agents
uv run gtz tail <sandbox-name>      # an agent's live session log
uv run gtz send <sandbox-name> "Status report please"
uv run gtz spend                    # GPU ledger vs ceiling
uv run gtz stop                     # delete every sandbox in the project
```

## Layout

- `groktimizer/core/` — Blaxel adapter (`blaxel_client.py`, the only module touching the SDK),
  label-based registry with cap enforcement, agent bootstrap, monitoring, budget-enforcing
  RunPod wrapper (`gpu.py`).
- `groktimizer/mcp/` — role-gated MCP server each agent runs.
- `groktimizer/cli/` — the `gtz` operator CLI.
- `groktimizer/prompts/` — role prompt templates.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — design spec and implementation plan.
- `scripts/smoke_e2e.md` — real-infrastructure smoke-test runbook.

## Status (2026-08-08)

Live-verified against real Blaxel sandboxes: create/labels/envs, registry + caps, exec
(stdout/exit codes/env visibility), file writes, monitoring, CLI tree/tail/stop, teardown;
grok 1.0.0 installs and runs in `blaxel/py-app:latest`, `grok mcp add` syntax confirmed.
Not yet exercised: RunPod provisioning against the real API, grok authenticated headless
runs (needs `XAI_API_KEY`), and the full multi-agent loop — see `scripts/smoke_e2e.md`.

---

## Baseline study: Grok-2 UD-TQ1_0 on one 96GB Blackwell

Serving and benchmarking Grok-2 at ~1.7 bits per weight on a single 96GB GPU.

The target artifact is `unsloth/grok-2-GGUF` at `UD-TQ1_0`, 81.8 GB on the Hub
(76.2 GiB on disk). It exists to fit a 270B-parameter MoE onto one card, and
this repo measures what that costs in latency, throughput, and accuracy.

### Hardware and software

| | |
|---|---|
| GPU | 1x NVIDIA RTX PRO 6000 Blackwell Server Edition, 96GB (sm_120) |
| Driver | 580.126.09, CUDA 12.8.93 |
| Host | Runpod secure cloud, US-NC-1, $2.09/hr |
| Engine | llama.cpp @ `687e778`, built with `CMAKE_CUDA_ARCHITECTURES=120` |
| Config | 64 layers all on GPU, 32768 context, `--jinja` |
| VRAM | 90.5 / 97.9 GB at 1 slot, 86.8 GB at 8 slots |

### Why llama.cpp and not vLLM or SGLang

Both were ruled out, for two independent reasons each.

Neither implements Grok-2. vLLM's model registry contains only
`Grok1ForCausalLM` and `Grok1ModelForCausalLM`. SGLang has a single `grok.py`
whose entry classes are the same two Grok-1 names.

Neither reads this file's quant types. vLLM's GGUF path is documented as
"highly experimental" and needs a separate `vllm-gguf-plugin`; SGLang lists
`gguf` among its methods but nothing covering i-quants.

Even setting both aside, Grok-2 in a format those engines serve is ~500GB at
BF16, which does not fit on one 96GB card in any quantization they support.

### What UD-TQ1_0 actually contains

The name is misleading. The file holds no `TQ1_0` tensors at all. It is
Unsloth's per-tensor dynamic mix:

| ggml type | tensors |
|---|---|
| F32 | 321 |
| IQ4_XS | 225 |
| IQ1_S | 142 |
| IQ3_XXS | 110 |
| IQ3_S | 108 |
| IQ2_XXS | 28 |
| Q5_K | 17 |
| Q6_K | 11 |
| Q4_K | 1 |

Architecture reports as `grok`, named `Grok-2`: 64 layers, 64 attention heads,
8 KV heads, 8192 embedding, 8 experts with 2 active, 131072 native context.

### Latency, single stream

Measured with prefix caching disabled and a unique prompt per trial. Median of
3. An earlier run with caching left on reported a flat ~40ms TTFT at every
prompt length, which is an artifact, not a result.

| prompt tokens | TTFT | decode tok/s | prefill tok/s |
|---:|---:|---:|---:|
| 133 | 775 ms | 25.3 | 172 |
| 497 | 1.10 s | 24.2 | 450 |
| 1,926 | 2.93 s | 25.8 | 658 |
| 7,666 | 11.81 s | 22.9 | 649 |

Decode is flat across context length, which points at weight-read bandwidth
rather than attention as the bottleneck. Prefill saturates near 650 tok/s, so
an 8k prompt costs about 12 seconds before the first token.

Flash attention is unavailable. llama.cpp logs
`flash_attn is not compatible with Grok - forcing off`, so this prefill ceiling
is a property of the architecture support, not a tuning gap.

### Output throughput vs concurrency

Server restarted with `-np 8`, 4096 context per slot. 200 generated tokens per
stream. Aggregate rate excludes prefill; each stream's clock starts at its own
first token.

| concurrency | aggregate out tok/s | per-stream tok/s | end-to-end tok/s | median TTFT |
|---:|---:|---:|---:|---:|
| 1 | 28.2 | 28.20 | 25.5 | 741 ms |
| 2 | 43.1 | 21.73 | 42.3 | 226 ms |
| 4 | 64.2 | 16.06 | 57.4 | 1,478 ms |
| 8 | 80.3 | 10.03 | 70.6 | 2,735 ms |

Batching buys 2.85x aggregate throughput at 8 streams, while per-stream rate
falls from 28 to 10 tok/s. Single-stream speed is not improvable by tuning
here; total tokens/sec is.

Slots were capped at 8 because of KV cache. At 64 layers, 8 KV heads and head
dim 128, this model costs 256 KiB per token at F16, and only ~7.3 GiB was free
at 1 slot. Going wider needs quantized KV, and V-cache quantization in
llama.cpp generally requires flash attention, which this architecture cannot
use.

### Accuracy

The server does not return prompt-token logprobs, so lm-evaluation-harness
loglikelihood scoring does not work against it. MMLU and ARC-Easy were run
0-shot generative with single-letter parsing instead. **These numbers are not
comparable to published loglikelihood MMLU and ARC results.**

| task | score | n | unparsed |
|---|---:|---:|---:|
| MMLU (0-shot, generative) | 68.7% | 150 | 0 |
| ARC-Easy (0-shot, generative) | 100.0% | 150 | 0 |

At n=150 the 95% interval is roughly ±7 to 8 points, so MMLU is somewhere in
the low-to-mid 60s through mid 70s.

ARC-Easy at 150/150 was verified rather than taken at face value: gold labels
are balanced across A through D, every item is 4-choice, and spot-checked
questions map correctly. It is a real score and a ceiling effect. ARC-Easy is
grade-school science and does not discriminate at this model size. It shows the
quant is coherent, not much more.

GSM8K did not run. lm-eval's chat path needs `--apply_chat_template`, which
was not passed before the slot was handed to the throughput sweep.

### Layout

```
bench/setup_pod.sh   provision, build llama.cpp for sm_120, download, serve
bench/bench.py       TTFT and single-stream decode across prompt lengths
bench/tput.py        aggregate output throughput vs concurrency
bench/mc_eval.py     generative multiple-choice eval (MMLU, ARC-Easy)
bench/make_chart.py  renders the throughput chart (light and dark SVG)
docs/                baseline write-up and figures
results/             raw JSON from the runs above
```

Full write-up with methodology and caveats:
[docs/grok-2-llama-cpp-baseline.md](docs/grok-2-llama-cpp-baseline.md).

### Reproducing

`bench/setup_pod.sh` runs end to end on a fresh Runpod pod with a persistent
volume at `/workspace`. Two things it handles that are easy to get wrong: `nvcc`
is not on `PATH` in the stock image, and Ubuntu 24.04 marks the system Python
externally managed, so pip needs `--break-system-packages`.

The model must live on the persistent volume. At 76.2 GiB it does not fit
container disk, and re-downloading it on every pod start is slow.

### Open items

Single-stream decode is bandwidth-bound and near its ceiling. The remaining
levers for total throughput are more concurrent slots, which needs KV headroom
that flash attention would have provided.

GSM8K still needs a run. Quantized KV cache is untested here and is the
gating experiment for concurrency above 8.
