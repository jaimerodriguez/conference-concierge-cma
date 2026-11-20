# Task guides

Short how-tos, one per feature. Each step names a file and a marker comment you can search
for. In the source, markers look like this:

```python
# Guide 05 · Wiring up OpenTelemetry · Step 2: register the tracer provider.
```

Search the repo for `Guide 05 ·` to see every step of a guide in place.

| # | Guide | Feature |
|---|---|---|
| 00 | [Setting up the project](00-setting-up.md) | uv, virtual environment, Ruff, tunnel |
| 01 | [Declaring an agent and applying it with the CLI](01-declaring-agents-with-ant-cli.md) | `ant apply`, lock file |
| 02 | [Versioning an agent and pinning sessions](02-versioning-and-pinning.md) | agent versions |
| 03 | [Creating an agent on the fly](03-agents-on-the-fly.md) | session overrides, runtime create |
| 04 | [Giving agents system-level memory](04-system-level-memory.md) | memory stores |
| 05 | [Wiring up OpenTelemetry](05-wiring-up-opentelemetry.md) | SDK and API tracing |
| 06 | [Storing secrets in a vault](06-storing-secrets-in-a-vault.md) | vault credentials |
| 07 | [Passing OAuth credentials from the client to an MCP server](07-oauth-credentials-for-mcp.md) | `mcp_oauth` |
| 08 | [Configuring your orchestrator for multi-agent](08-multi-agent-orchestrator.md) | roster, workflows |
| 09 | [Adding an advisor](09-adding-an-advisor.md) | advisor |
| 10 | [Scheduling an agent](10-scheduling-an-agent.md) | scheduled deployments |
| 11 | [Grading work with outcomes](11-grading-with-outcomes.md) | outcomes |
| 12 | [Approvals and budgets](12-approvals-and-budgets.md) | permission policies, budgets |
| 13 | [Moderating user input](13-moderating-user-input.md) | structured output |
| 20 | [Moving tools into your own sandbox](20-self-hosted-sandbox.md) | self-hosted sandboxes |
| 21 | [Migrating to self-hosted Managed Agents](21-migrating-to-self-hosted-managed-agents.md) | self-hosted service |

Guides 00 to 13 are phase 1 (hosted). Guides 20 and 21 are phase 2 (self-hosted).
