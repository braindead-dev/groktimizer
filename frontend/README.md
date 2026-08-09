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
- `app/api/` — local/remote gateway for control-plane snapshots, agent streams, and steering
- `components/` — dashboard, chat, navigation, charts, and role-specific workspaces
- `lib/control-plane-*` — typed browser/server bridge to the local CLI or remote HTTP service
- `store/research-store.tsx` — reducer-backed live registry and committed-baseline state

## Live mode

When the repository root contains `groktimizer.toml` and the required Blaxel credentials, the
app loads `gtz snapshot`, maps the live sandbox registry into the project tree, and opens an SSE
stream for the selected agent. Steering remains a normal POST that delegates to `gtz send`.

The backend's exec channel is request/response, so the Python `gtz watch` bridge polls that source
inside one long-lived process and emits JSONL. In local mode, the Next.js route translates JSONL to
browser-native SSE. In production mode it requests a short-lived, sandbox-scoped stream ticket and
redirects the browser directly to the persistent API, avoiding a long-running Vercel function.

Baseline charts use the real `results/*.json` artifacts from the repository configured as
`shared_repo` in `groktimizer.toml`. The server reads a local checkout when present and otherwise
uses the authenticated GitHub Contents API, cached for one minute. It does not create mock projects,
agents, messages, experiments, or compute utilization.

Set `GTZ_CONTROL_PLANE_URL` and `GTZ_CONTROL_PLANE_TOKEN` as server-only Vercel variables to enable
remote mode. Neither variable uses `NEXT_PUBLIC_`, and provider credentials never enter Vercel.

Deleting a project requires explicit confirmation and removes its Blaxel sandboxes, attributed
RunPod resources, and SQLite activity state. Git branches and committed research artifacts remain
available for audit or a clean restart.
