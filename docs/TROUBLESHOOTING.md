# Troubleshooting

Find your symptom, check the cause, run the fix. **First step for anything odd:**

```sh
uv run concierge doctor      # checks the files, the applied agents, the vault and the deployment
```

Doctor marks real problems `todo` (it exits with an error), harmless leftovers `note`, and
checks it could not make `skip` (with the reason). Run it from anywhere inside the repo.

## What can still go wrong

### "the server host could not be resolved or reached"
Seen as `MCP server 'eventdb' initialize failed: the server host could not be resolved or reached`.

**Cause.** Anthropic's cloud cannot open your tunnel address: `concierge serve` is not running,
the tunnel is not running, or the address in `.env` is not the one the tunnel prints now.

**Fix.** Keep both running (`uv run concierge serve` and `cloudflared tunnel --url
http://localhost:8000`). Open `https://<your-host>/` in a browser: you should see the proposal
form. If the host is different from `.env`, see the next item.

### The tunnel address changed (free `cloudflared` addresses change on every restart)
Symptoms: the item above, or `doctor` todos such as "managed/ files use the host in .env" and
"the vault has a credential for https://…".

**Fix.** Put the new address in `.env` (full `https`, no trailing slash), restart `serve`, then:

```sh
uv run concierge setup all     # rewrites the host, re-applies, re-stores credentials, signs in again
```

A named Cloudflare tunnel or a reserved ngrok domain keeps one address and avoids this.

### "no credential is stored for this server URL"
Seen as `initialize failed: no credential is stored for this server URL — check that the agent's MCP
server URL matches the URL in the vault`.

**Cause.** The session had no vault, or the vault has no credential for the exact URL the agent
calls. After a run, the CLI prints which vaults the session had and which URLs they hold.

**Fix.** `uv run concierge setup all` (or `setup vault` and `auth calendar` for the credentials,
`setup deployment` and `ant apply` from `managed/` if the deployment has no vault). Credentials
match by exact URL (same scheme, host and path), so a stale address means a missing credential.

### Credential hosts: "…hosts that the environment's network policy does not permit"
**Cause.** A secret (`environment_variable`) credential lists a host the environment's
`allowed_hosts` does not. Every new session reports it and the secret cannot be used.

**Fix.** `uv run concierge setup vault` resets the credential's hosts to your address (doctor
shows them), then start a **new** session: running sessions keep the old settings.

### Changes seem ignored
A session takes the agent version, environment and vault credentials as they were **when it
started**. After `ant apply`, `setup vault` or `auth calendar`, start a new run.

### `ant apply` was run from the repo root
**Symptom.** Extra agents, a second vault, or phase 2 resources (`self-hosted.yaml`, the
`phase2/` agents) appear in your workspace.

**Cause.** `ant apply` walks every folder below where you run it. Always run it from inside
`managed/` (`setup all` does this for you).

**Fix.** Remove the extra resources in the Console (deleting is permanent: archive or delete only
the ones you did not intend), then run `setup all` from the repo root.

### Resources deleted by hand, or `managed/claude-lock.json` deleted
**Symptoms.** `ant apply` errors about missing resources, `doctor` shows "could not check"
with a NotFound error, or `apply` creates a second copy of everything.

**Cause.** The lock file maps each file to the ID it was given. If an ID no longer exists, or the
lock is gone, `ant` cannot match files to resources.

**Fix.** Delete the lock file **only after** you have deleted the matching resources in the
workspace (otherwise you get duplicates). Then run `setup all` to recreate everything.

### Resources appeared in the wrong workspace
**Cause.** Resources go to the workspace your `ant` profile or `ANTHROPIC_API_KEY` belongs to.
`CONCIERGE_WORKSPACE` in `.env` only builds Console links.

**Fix.** Check with `ant auth status`; switch profile (`ant profile activate …`) or key, delete
`managed/claude-lock.json` after cleaning up the old workspace, and run `setup all`.

### `doctor` note: leftover vault credential
A credential stored for an address you no longer use. It is ignored and harmless. Remove it with
`uv run concierge setup vault --remove-stale` (asks first; deleting is permanent).

### `doctor` note: Calendar access token is past its expiry
The mock server's access tokens expire after 15 minutes, on purpose (Guide 07). A stored
refresh token lets Anthropic renew
it when the Calendar is used, so this alone is not a failure. If the Calendar then reports an
auth error, run `uv run concierge auth calendar`.

### `ant` not found, or `ant apply --dry-run` unknown
`doctor` shows a `skip` for the apply comparison, and `setup all` stops at the first apply. Install
or upgrade `ant` (1.40.0 or later, see the README prerequisites).

## What the code now prevents or catches

These were real problems during setup; you should not hit them any more:

| Problem | How it is handled |
| --- | --- |
| Agent files still use the sample host `concierge.example.com` (HTTP 400 at `initialize`) | `concierge` stops with the fix before starting a session; `doctor` flags it |
| `.env` address uses `http://` | `setup host` refuses it; `doctor` flags it |
| Host typed differently in `.env`, the state file, `managed/` or the phase 2b copies | `setup host` reads the host from `.env`; `doctor` compares every copy and the applied agents |
| Commands behave differently depending on the folder you run them in | Paths are anchored to the repo; output is the same from anywhere |
| `review run` starts with no vault (deployment `vault_ids` empty) | `setup deployment` (part of `setup all`); `doctor` checks the file and the applied deployment |
| Stored secret keeps an old host after the address changes | `setup vault` resets the hosts when it rotates; `doctor` shows and checks them |
| False "files changed since the last apply" warning | `doctor` asks `ant apply --dry-run` instead of comparing file times |
| Sessions explained as "MCP error" when the cause was something else | Errors are explained by type (MCP vs credential hosts) after each run |
| Setup steps run in the wrong order | `setup all` runs them in order and stops at the first failure |
