# Guide 02 · Versioning an agent and pinning sessions

**You'll learn:** that an agent is a versioned resource, and how sessions choose a version.

## Steps

**Step 1. Change the agent's file.** For example, tell the Attendee Helper to answer in one
sentence instead of two or three.
Find it: `managed/agents/attendee-helper/agent.md`, marker `Guide 02 · ... · Step 1`.

**Step 2. Apply.** (No marker: commands.) The agent keeps its ID and gets the next version
number.

```sh
cd managed && ant apply agents/attendee-helper/agent.md
ant beta:agents:versions list --agent-id "$(jq -r '.resources["./agents/attendee-helper/agent.md"].id' claude-lock.json)"
```

**Step 3. Choose a version per session.** A bare agent ID means "latest at session
creation". An explicit version pins the session.
Find it: `src/concierge/attendee.py`, marker `Step 3`.

## Try it
```sh
uv run concierge ask "Where do I park?"                                  # latest version
CONCIERGE_HELPER_AGENT_VERSION=1 uv run concierge ask "Where do I park?"  # pinned to version 1
```

## What to notice
- Sessions already running keep the version they started with. Updating an agent never
  changes a session in flight.
- Pinning is also your rollback: point new sessions at the last good version while you fix
  the prompt.
- A coordinator lists its subagents at a version too. Applying the coordinator's file again
  picks up a subagent's new version.
