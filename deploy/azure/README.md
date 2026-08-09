# Azure control-plane deployment

The production topology is one supervised API process behind Caddy. Provider credentials live in
Azure Key Vault and are loaded at boot using the VM's managed identity. SQLite lives on a separate
managed data disk mounted at `/var/lib/groktimizer`; Azure Backup protects the whole VM.

Deployed resources use these roles:

- `groktimizer-api`: Ubuntu VM running Caddy and `groktimizer-api.service`
- `groktimizer-data`: managed data disk containing the SQLite store
- `groktimizer-kv-*`: RBAC-enabled Key Vault containing provider and gateway secrets
- `groktimizer-backup-vault`: Recovery Services vault with daily VM backups

The host is updated from the public `main` branch:

```bash
sudo git -C /opt/groktimizer fetch origin main
sudo git -C /opt/groktimizer reset --hard origin/main
sudo chown -R groktimizer:groktimizer /opt/groktimizer
sudo -u groktimizer uv sync --directory /opt/groktimizer --frozen --no-dev
sudo systemctl restart groktimizer-secrets.service groktimizer-api.service
```

Operational checks:

```bash
curl -fsS https://API_HOST/healthz
sudo systemctl status groktimizer-api caddy
sudo journalctl -u groktimizer-api -n 100 --no-pager
sudo sqlite3 /var/lib/groktimizer/groktimizer.db 'PRAGMA integrity_check;'
```

Only `GTZ_CONTROL_PLANE_URL` and `GTZ_CONTROL_PLANE_TOKEN` belong in Vercel. Both are server-only;
never use a `NEXT_PUBLIC_` prefix. Set `GTZ_DASHBOARD_USERNAME` and `GTZ_DASHBOARD_PASSWORD` there
as well to protect the operator UI. Provider keys remain in Azure Key Vault.
