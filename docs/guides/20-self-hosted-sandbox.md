# Guide 20 · Moving tools into your own sandbox

**You'll learn:** how to run the agents' tools in a container you own while Anthropic keeps
running the agent loop. This is phase 2a.

**The story:** the meetup grows into a conference series, and the security team wants
attendee data and tool execution to stay inside the company network.

```
 Anthropic: agent loop, sessions, history, vaults
        ▲  work queue (the worker dials out; nothing dials in)
        │
 Your network: worker container ── runs bash, file tools ── your data
               your client ─────── runs custom tools ────── your secrets
```

## Steps

**Step 1. Declare a self-hosted environment.** `{type: self_hosted}` is the whole
configuration. Networking and capacity are now yours to control.
Find it: `managed/environments/self-hosted.yaml`, marker `Guide 20 · ... · Step 1`.

**Step 2. Run the worker.** It authenticates with an *environment key*, which grants
access to this one environment's work queue. Your Claude API key does not belong on the
worker host.
Find it: `phase2/a-self-hosted-sandbox/docker-compose.yml` and `worker.py`, marker `Step 2`.

**Step 3. Swap the vaulted secret for a custom tool.** Phase 1 stores the sponsor's API
key as an `environment_variable` credential that Anthropic substitutes on the way out of
the cloud sandbox. Your sandbox has its own egress, so the Speaker Liaison gets a variant
with a custom tool, `issue_perk_code`.
Find it: `managed/agents/speaker-liaison-host-tool/agent.md`, marker `Step 3`.

**Step 4. Execute the custom tool in your own process.** The agent asks for the tool, your
client (which holds the key) makes the call, and only the result goes back.
Find it: `src/concierge/perks.py` and `src/concierge/sessions.py`, marker `Step 4`.

**Step 5. Emit tool spans from the worker.** Tools now run in your process, so their spans
come from there too.
Find it: `phase2/a-self-hosted-sandbox/worker.py`, marker `Step 5`.

## Try it
```sh
cd managed && ant apply --yes && cd ..          # creates the self-hosted environment
uv run concierge setup show                     # prints its env_... ID

cd phase2/a-self-hosted-sandbox
export ANTHROPIC_ENVIRONMENT_ID=env_...
export ANTHROPIC_ENVIRONMENT_KEY=...            # from the environment's page in the Console
docker compose up --build
```
In another terminal, with `CONCIERGE_ENVIRONMENT=self-hosted` in `.env`:
```sh
uv run concierge ask "Where do I park?"
uv run python phase2/a-self-hosted-sandbox/issue_perks.py
```

## What you keep, what you lose

| Feature | Hosted (phase 1) | Self-hosted sandbox (2a) |
|---|---|---|
| Agents, versions, overrides | ✅ | ✅ unchanged |
| Multi-agent, advisor, workflows | ✅ | ✅ unchanged |
| Scheduled deployments | ✅ | ✅ unchanged |
| `mcp_oauth` and `static_bearer` credentials | ✅ | ✅ unchanged |
| `environment_variable` credentials | ✅ substituted at egress | ❌ use a host-side custom tool |
| Memory stores | ✅ live mount | ✅ the SDK worker syncs files on an interval |
| Session file resources | ✅ | ❌ only memory stores attach |
| Tool-call traces | From Anthropic | From your worker |
| Scaling, patching, egress rules | Anthropic's job | Your job |

## What to notice
- The agents did not change, apart from the one that used an egress-substituted secret.
- Stop the worker with `docker compose stop`, not `kill -9`. On a clean stop it finishes
  in-flight work and uploads changed memory files.
- The container in this repo is hardened in basic ways (read-only root, no capabilities).
  It can still reach whatever your network allows, so restrict egress to what agents need.
