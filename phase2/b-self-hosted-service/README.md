# Phase 2b: self-hosted Managed Agents (the service)

You run the API, the agent loop, and the storage (`cma-server` plus PostgreSQL), and the
workers. This part is **not demoed live**: the server release comes through your Anthropic
account team. It ships as source and a migration guide:
[Guide 21](../../docs/guides/21-migrating-to-self-hosted-managed-agents.md).

| File | What it is |
|---|---|
| `make_managed.py` | Derives this phase's resource files from `managed/` and prints every change |
| `managed/` | The generated files, committed so you can read the result |
| `env.selfhosted.example` | Variables that point the SDK, `ant`, and the demo at your server |
| `server-settings.example.yaml` | Server settings the demo needs (MCP host allow list) |
| `cron/daily-review.cron` | The cron entry that replaces the scheduled deployment |
