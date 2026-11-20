# Guide 01 · Declaring an agent and applying it with the CLI

**You'll learn:** how to keep agents, environments, memory stores, vaults, and deployments as
version-controlled files, and sync them with `ant apply`.

## Steps

**Step 1. Declare the agent.** An agent file is YAML frontmatter (the configuration) plus a
Markdown body (the system prompt).
Find it: `managed/agents/program-chair/agent.md`, marker `Guide 01 · ... · Step 1`.
The other agents in `managed/agents/` follow the same shape.

**Step 2. Declare the environment.** The sandbox template sessions start from: networking
mode and the hosts the sandbox may reach.
Find it: `managed/environments/cloud.yaml`, marker `Step 2`.

**Step 3. Apply.** Run from inside `managed/`, so `claude-lock.json` is written there. Do not run it from the repo root: `ant apply` walks every folder below where you run it, so it would also apply the phase 2 files under `phase2/`. Look at the
plan first, then apply. (No marker: this step is commands.)

```sh
cd managed
ant apply --dry-run -v agents environments memory_stores vaults    # the plan, nothing changes
ant apply agents environments memory_stores vaults                 # asks before applying
```

`ant apply` also applies what a file references, in dependency order: the Program Chair
lists its subagents by path, so they are created first and their IDs are filled in. The
deployment is applied later (Guide 10), because it needs the vault's ID.

**Step 4. Read the IDs back in code.** `claude-lock.json` maps each file to the ID it was
given. Do not commit it (it is in `.gitignore`): it lists the IDs in *your* workspace, so each
person keeps their own. The next `ant apply` uses it to update the same resources.
Find it: `src/concierge/managed.py`, marker `Step 4`.

## Try it
```sh
uv run concierge setup show        # the table of files and IDs
```

## What to notice
- Reference other resources by **path**, not ID. `vault_ids` on a deployment is the one
  exception.
- To change a resource, edit its file and apply again. Do not edit it in the Console as well:
  a change made outside the files makes the next `ant apply` refuse to run.
- A resource created another way (Console, SDK) cannot be adopted by a file.
- Credentials, uploaded files, and sessions are not managed by `ant apply`.
