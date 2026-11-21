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
- **The sandbox only ever holds a stand-in for the key.** Inside the sandbox,
  `$CLOUDCREDITS_API_KEY` contains a placeholder (a random string that starts with `cma_ph_`),
  which is why the echo prints that instead of the key. When `curl` puts the placeholder in a
  request header, Anthropic's network proxy swaps it for the real key once the request has
  left the sandbox and is on its way to the CloudCredits API. Nothing inside the sandbox (the
  agent, its shell, its files) ever sees the real value.
- **The swap only happens where you allow it.** The proxy replaces the placeholder only on
  requests to the credential's `allowed_hosts`, and only in the parts of the request that
  `injection_location` allows. This demo allows headers only (Step 3). A placeholder anywhere
  else, such as the request body or the URL, is sent unchanged, so the real key is never used there.
- A service that echoes request headers back would hand the real key to the sandbox. Allow
  only hosts you trust.
- Secret fields are write-only: the API never returns them. Running `setup vault` again
  rotates them in place.
- **This only works in Anthropic's cloud sandbox.** The swap is done by Anthropic's proxy,
  which sits between the cloud sandbox and the internet. A sandbox you host yourself (Phase 2)
  reaches the internet through your own network, so no Anthropic proxy is in the path to make
  the swap, and `setup vault` skips this credential there. Guide 20 replaces it with a custom
  tool that runs in your own process and holds the key. Guide 21 covers the self-hosted
  service, which can do the same swap only if you turn on its egress gateway.
- **Removing old credentials.** If your services move to a new address (say, a new tunnel),
  the credentials stored for the old MCP server URLs stay in the vault. They do no harm: a
  session only uses a credential whose URL matches one of the agent's MCP servers, so old ones
  are never picked. `setup vault` and `concierge doctor` both list these leftovers. To delete them:
  ```sh
  uv run concierge setup vault --remove-stale
  ```
  It shows what it will delete and asks first, because deleting is permanent (`--yes` skips
  the question).
