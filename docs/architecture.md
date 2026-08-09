# Architecture

Groktimizer separates execution, durable state, transport, and presentation so each layer has one
source of truth.

## Runtime topology

```text
Next.js operator UI
        │ server-only bearer auth
        ▼
FastAPI control plane ───── Azure Key Vault
        │
        ├── SQLite on a dedicated managed disk
        ├── Blaxel sandbox registry and agent runners
        ├── RunPod GPU provisioning behind budget policy
        └── GitHub branches and measured result artifacts
```

The production API runs as a supervised systemd service behind Caddy. Provider credentials are
loaded from Key Vault by the VM's managed identity into a root-owned runtime directory. The browser
never receives the API bearer token or provider credentials.

## Sources of truth

- **Blaxel labels** answer which remote sandboxes are alive. Sandbox names follow
  `gtz-{project}-{team}-{agent}`.
- **SQLite** owns durable projects, agent identities, ordered turns, structured tool/output events,
  runtime cursors, and validated research documents.
- **Git** owns code, experimental branches, and reproducible benchmark artifacts.
- **RunPod** owns transient GPU processes. GPU state is never used as the project database.

Polling reconciles live Blaxel state into SQLite. A disappearing sandbox is marked terminated; its
conversation and branch pointer remain available for audit.

## Research records

`groktimizer.core.research_record` defines the versioned Pydantic schema for source-linked research
programs. Importing a record is idempotent and transactional at the project level:

1. Validate the complete document before mutating state.
2. Upsert projects and exact display titles.
3. Persist team and agent identities using the normal sandbox naming contract.
4. Write ordered turns, reasoning, tool results, and runtime cursors through the normal store APIs.
5. Attach metric series and promotion decisions to each project as one validated document.

The frontend contains no Grok-specific project fixtures. It projects either a live registry snapshot
or an installed research document into the same `Project`, `ResearchTeam`, and `Agent` view models.

## Realtime transport

Live agents stream structured runner deltas. Persisted research sessions replay their ordered event
history and then maintain the same SSE connection/status/heartbeat contract. Both paths use
short-lived, sandbox-scoped stream tickets, so Vercel never holds a long-running function open and
the durable API token stays server-side.

Event ordering is monotonic by the stored remote sequence. Tool updates retain their call identity,
allowing the UI to group contiguous calls while preserving interleaved reasoning and assistant text.

## Frontend boundaries

- `app/api/` is the server-only gateway to local CLI mode or the remote API.
- `lib/control-plane-types.ts` is the wire contract.
- `store/research-store.tsx` normalizes wire data into presentation models.
- `components/` render those models and never fetch provider APIs directly.

Polling refreshes project topology every ten seconds. Each selected agent has its own SSE stream for
lower-latency conversation and status updates.

## Durability

- SQLite uses WAL mode and a five-second busy timeout.
- Schema upgrades create a timestamped database backup before migration.
- Azure mounts the database on a separate Premium SSD.
- systemd restarts the API and secret loader after failures or VM reboots.
- Azure Backup creates daily filesystem-consistent recovery points with 30-day retention.

Project deletion is explicit and confirmed. It tears down attributed sandboxes and GPU resources,
removes durable activity state, and leaves Git branches recoverable.
