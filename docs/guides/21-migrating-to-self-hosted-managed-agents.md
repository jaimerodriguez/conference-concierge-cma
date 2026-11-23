# Guide 21 · Migrating to self-hosted Managed Agents

**You'll learn:** what changes when you run the Managed Agents service itself: the API, the
agent loop, and storage in your own PostgreSQL. This is phase 2b.

**This part is source and instructions, not a live demo, because the feature is gated.**
To get access to self-hosted Managed Agents, contact your Anthropic account team.

The differences from phase 1 are deliberate: this guide is a map of what you keep and
what you give up.
Reference: <https://platform.claude.com/docs/en/managed-agents/self-hosted>

**The story:** the company now wants agent definitions and session history stored in its
own database, and model calls routed through its own gateway or cloud provider.

## What you keep, what you lose

| Feature | Hosted (phase 1) | Self-hosted service (2b) | What the demo does |
|---|---|---|---|
| Agents via `ant apply` | ✅ | ✅ recreate on your server | Generated files, applied again |
| On-the-fly agents | ✅ | ✅ | Unchanged |
| Memory stores | ✅ | ✅ the worker syncs | Unchanged, seeded again |
| Coordinator with a roster | ✅ | ✅ `{type: coordinator, agents: [...]}` | Block rewritten |
| Dynamic workflows | ✅ | ❌ | The chair reviews through the roster |
| Advisor | ✅ | ❌ | The chair checks agenda balance itself |
| Scheduled deployments | ✅ | ❌ | A cron entry runs `review run --direct` |
| `mcp_oauth` credentials | ✅ auto-refresh | ❌ | Calendar takes a fixed token you rotate |
| `environment_variable` credentials | ✅ | ⚠️ only with the egress gateway | Host-side custom tool (Guide 20) |
| MCP servers | ✅ | ⚠️ hosts must be allow-listed | `mcp.allowed_hostnames` |
| Files API and output capture | ✅ | ❌ | Results read from the agent's reply |
| Cloud environments | ✅ | ❌ self-hosted workers only | The worker from Guide 20 |
| Webhooks | ✅ | ❌ | Not used |
| Console session viewer | ✅ | ❌ your own tooling | Printed links do not apply |
| Inference provider | Claude API | Claude API, a cloud provider, or your gateway | Your choice |
| Where history lives | Anthropic | Your PostgreSQL | |

## Steps

**Step 1. Derive the resource files.** A script rewrites `managed/` for the server and
prints every change, so the differences are visible as a diff, not hidden in prose.
```sh
uv run python phase2/b-self-hosted-service/make_managed.py
```
Find it: `phase2/b-self-hosted-service/make_managed.py`, marker `Guide 21 · ... · Step 1`.
The result is committed in `phase2/b-self-hosted-service/managed/`.

**Step 2. Point the SDK and the `ant` CLI at your server.** Two variables: the base URL
and the *server's* API key. No code changes.
Find it: `phase2/b-self-hosted-service/env.selfhosted.example`, marker `Step 2`.

**Step 3. Apply the generated files and use the server's environment.** Nothing copies
over from the hosted workspace: agents, memory stores, and vaults are created again.
```sh
set -a && . ./.env.selfhosted && set +a
cd phase2/b-self-hosted-service/managed && ant apply --yes && cd -
uv run concierge setup memory && uv run concierge setup vault
```
Find it: `phase2/b-self-hosted-service/env.selfhosted.example`, marker `Step 3`.

**Step 4. Allow the MCP hosts in the server settings.** The list is empty by default and
matching is exact.
Find it: `phase2/b-self-hosted-service/server-settings.example.yaml`, marker `Step 4`.

**Step 5. Replace OAuth with a fixed token.** Without `mcp_oauth` there is no automatic
refresh. The Calendar server accepts a static token when one is configured, and
`concierge setup vault` stores it as a `static_bearer` credential. Rotation is your job.
Find it: `phase2/b-self-hosted-service/env.selfhosted.example`, marker `Step 5`.

**Step 6. Replace the deployment with cron.** Your scheduler starts the session with the
same kickoff the hosted deployment used.
Find it: `phase2/b-self-hosted-service/cron/daily-review.cron`, marker `Step 6`.

## Verify against your release
The public "differences" page does not cover everything this demo uses. Check these in the
operator guide that ships with your server version before you rely on them:

- **OpenTelemetry**, **outcomes**, **permission policies** (including `auto`), and
  **session budgets**: the page does not say how they behave on a self-hosted server.
- The setting that enables the **egress gateway** for `environment_variable` credentials.
- Whether `ant apply` accepts **file paths inside `coordinator.agents`**, as it does for
  rosters on the hosted service. If not, replace the paths with agent IDs.

## What to notice
- The Python code is the same in both phases. The differences live in configuration:
  generated resource files, a handful of environment variables, and one cron line.
- A test (`tests/test_core.py`) fails when the committed phase 2b files drift from what the
  generator produces.
- Hosted gives you scheduling, OAuth refresh, workflows, the advisor, and a session viewer
  for free. Self-hosting trades those for control over where data and model calls go.
