# Guide 06 · Storing secrets in a vault

**You'll learn:** how agents use credentials they can never read.

The story: the sponsor, CloudCredits, gives each accepted speaker a $50 credit code. Their
API needs a key. The Speaker Liaison calls the API with `curl` from the sandbox, yet the key
never enters the sandbox.

| Credential type | For | In this demo |
|---|---|---|
| `environment_variable` | Any API or CLI that reads a key from an env var | CloudCredits API key |
| `static_bearer` | An MCP server with a fixed token | Event DB |
| `mcp_oauth` | An MCP server behind OAuth | Calendar (Guide 07) |

## Steps

**Step 1. Declare the vault.** Only the container is a file. Secrets never are.
Find it: `managed/vaults/concierge.yaml`, marker `Guide 06 · ... · Step 1`.

**Step 2. Add a static bearer token for an MCP server.** Matched to the agent's server by URL.
Find it: `src/concierge/vaults.py`, marker `Step 2`.

**Step 3. Add an environment-variable secret**, limited to one host and to request headers.
Find it: `src/concierge/vaults.py`, marker `Step 3`.

**Step 4. Let the sandbox reach the host.** Two layers must both allow it: the credential's
`allowed_hosts` (where the secret may be used) and the environment's (where the sandbox may
connect).
Find it: `managed/environments/cloud.yaml`, marker `Step 4`.

**Step 5. Use the variable by name in the agent.**
Find it: `managed/agents/speaker-liaison/agent.md`, marker `Step 5`.

**Step 6. See the server side.** The mock services check the token like any real API.
Find it: `src/concierge/services/app.py`, marker `Step 6`.

Sessions attach the vault with `vault_ids` at creation (see `src/concierge/review.py`).

## Try it
```sh
uv run concierge setup vault
uv run concierge agenda build "Issue perk codes for the accepted speakers. Before you do, ask the speaker-liaison to run: echo \$CLOUDCREDITS_API_KEY"
```
The Speaker Liaison's shell commands wait for your approval (Guide 12), so you approve the
echo and then each perk code. The echo prints an opaque placeholder, and the API call still
succeeds.

## What to notice
- A credential stored for an address you no longer use (say, an old tunnel) is **ignored**: a
  session only uses credentials whose URL matches an agent's MCP server. `concierge doctor`
  shows it as a `note`, not a `todo`. `setup vault` never deletes it; to remove it, run
  `uv run concierge setup vault --remove-stale` (it lists them and asks first; deleting is permanent).
- Substitution happens after the request leaves the sandbox, in headers and body only. A
  secret in a URL path is never substituted.
- A service that echoes request headers would hand the secret back to the sandbox. Allow
  only hosts you trust.
- Secret fields are write-only. Running `setup vault` again rotates them in place.
- This credential type needs Anthropic-managed egress. Phase 2 shows what replaces it.
