# Groktimizer frontend

Interactive Next.js command center for Groktimizer.

## Run locally

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Structure

- `app/` — Next.js App Router entrypoint and the visual system
- `app/api/` — local gateway for control-plane snapshots, agent streams, and steering
- `components/` — dashboard, chat, navigation, charts, and role-specific workspaces
- `lib/control-plane-*` — typed browser/server bridge to the Python operator CLI
- `store/research-store.tsx` — reducer-backed live registry and committed-baseline state

## Live mode

When the repository root contains `groktimizer.toml` and the required Blaxel credentials, the
app loads `gtz snapshot`, maps the live sandbox registry into the project tree, and opens an SSE
stream for the selected agent. Steering remains a normal POST that delegates to `gtz send`.

The backend's exec channel is request/response, so the Python `gtz watch` bridge polls that source
inside one long-lived process and emits JSONL. The Next.js route translates JSONL to browser-native
SSE with reconnect semantics. No second registry or persistent web service is introduced.

Baseline charts use the real `results/*.json` artifacts from the repository configured as
`shared_repo` in `groktimizer.toml`. The server reads a local checkout when present and otherwise
uses the authenticated GitHub Contents API, cached for one minute. It does not create mock projects,
agents, messages, experiments, or compute utilization.

This hackathon control plane supports one active project in the configured research repository.
Deleting a project requires an explicit second confirmation and removes only its Blaxel sandboxes;
Git branches and committed research artifacts remain available before a clean restart.
