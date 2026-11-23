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
access to this one environment's work queue. An environment key is like a Claude API key,
but it's specific to the environment. Create it in the Anthropic Console: find your
environment (concierge-self-hosted), click on it, then click "Generate environment key".

Find it: `phase2/a-self-hosted-sandbox/docker-compose.yml` and `worker.py`, marker `Step 2`.

**Step 3. Swap the vaulted secret for a custom tool.** Phase 1 stores the sponsor's API
key as an `environment_variable` credential that Anthropic substitutes on the way out of
the cloud sandbox. Since you are no longer using Anthropic's cloud sandbox, you must now
handle that key yourself. For this, the Speaker Liaison gets a custom tool, `issue_perk_code`.
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
export ANTHROPIC_ENVIRONMENT_ID=env_...         # environments/self-hosted.yaml row of `setup show`
export ANTHROPIC_ENVIRONMENT_KEY=...            # generated on the environment's page in the Console
docker compose up --build
```
The worker needs only those two variables, and it does not read the top-level `.env`.
Instead of exporting them, you can copy `phase2/a-self-hosted-sandbox/.env.example` to
`.env` in that folder (git-ignored) and fill them in; `docker compose` reads it from there.

In another terminal, with `CONCIERGE_ENVIRONMENT=self-hosted` in `.env`:
```sh
uv run concierge setup vault    # takes the CloudCredits key out of the vault (see below)
uv run concierge ask "Where do I park?"
uv run python phase2/a-self-hosted-sandbox/issue_perks.py
```
A self-hosted session is refused if its vault holds any `environment_variable`
credential, so `setup vault` deletes the CloudCredits key that phase 1 stored. The value
stays in `.env`: to go back to phase 1, set `CONCIERGE_ENVIRONMENT=cloud` and run
`setup vault` again.

### What to look for

**After `concierge ask`**, the CLI's last line says the tools ran in your worker:
```
Environment: self-hosted. Built-in tools (read, grep, bash...) ran in your worker
container: its terminal shows each one.
```
The proof is in the terminal running `docker compose up`. The worker claims the session,
mounts its memory stores, and logs each tool call with what it ran on:
```
08:19:07 INFO claimed work work_id=sesn_01AXDH... work_type=session
08:19:08 INFO downloaded 2 memories memory_store_id=memstore_... -> /mnt/memory/venues
08:19:08 INFO downloaded 2 memories memory_store_id=memstore_... -> /mnt/memory/ops-notes
08:19:08 INFO session tool runner starting session_id=sesn_01AXDH...
08:19:08 INFO tool ran in this container: read /mnt/memory/venues/harbor-tech-hub.md   <- the answer came from here
08:19:09 INFO tool ran in this container: glob /mnt/memory/ops-notes/**/*
08:20:10 INFO session idle for 60s after its turn ended; stopping
08:20:10 INFO removed memory store dir /mnt/memory/venues memory_store_id=memstore_...
```
The `tool ran in this container` lines are the point: the venue file was read on your
machine, not in Anthropic's cloud. The worker holds each session for 60 seconds after its
turn ends, in case you send a follow-up, then uploads changed memory files and lets it go.

**After `issue_perks.py`**, the script's own output shows each step, and marks the custom
tool calls it ran itself:
```
[Speaker Liaison] reading the accepted proposals
[Speaker Liaison] looking up members
[Speaker Liaison] issuing a perk code for mem_c70db5ef (runs in this script, not the worker)
[Speaker Liaison] issuing a perk code for mem_3bfb65ee (runs in this script, not the worker)
...
[Speaker Liaison] recording a perk code for mem_c70db5ef
```
The worker claims this session too, but runs nothing for it. It sees each custom tool
call and leaves it for your script:
```
08:27:20 INFO claimed work work_id=sesn_01RazC... work_type=session
08:27:23 INFO custom tool issue_perk_code runs in your client, not here (tool_use_id=sevt_01RG5H...)
```
That is expected, not an error: the Speaker Liaison variant has the built-in tools turned
off, its Event DB calls go through Anthropic's MCP connection, and `issue_perk_code` runs
in your script, which holds the sponsor key. (The SDK's own wording for this line is
"not owned by this runner"; `worker.py` rewords it.)

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
