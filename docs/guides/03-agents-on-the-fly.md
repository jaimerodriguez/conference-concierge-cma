# Guide 03 · Creating an agent on the fly

**You'll learn:** the two ways to get an "inline" agent. Every session must reference a
stored agent, so on-the-fly means one of:

| Way | Use it when | In this demo |
|---|---|---|
| **Per-session overrides** | One base agent, different prompt or model per request | Abstract Writer |
| **Create at runtime** | Your app provisions agents itself (one per customer, say) | Speaker Bio Writer |

## Steps

**Step 1. Keep a minimal stored base agent.**
Find it: `managed/agents/abstract-writer/agent.md`, marker `Guide 03 · ... · Step 1`.

**Step 2. Override it for one session.** `agent_with_overrides` replaces `system` (built from
the persona and track) for that session only. No new agent, no new version.
Find it: `src/concierge/abstracts.py`, marker `Step 2`.

**Step 3. Create an agent from code, guarded.** Look for a saved ID before creating.
Find it: `src/concierge/bios.py`, marker `Step 3`.

**Step 4. Avoid duplicates when local state is lost.** Look the agent up by name.
Find it: `src/concierge/bios.py`, marker `Step 4`.

**Step 5. Persist the ID** so every later run reuses the same agent.
Find it: `src/concierge/bios.py`, marker `Step 5`.

## Try it
```sh
uv run concierge propose "Model distillation" --persona data-engineer --track lightning
uv run concierge bio "Sam" "Builds weather stations from spare parts; first-time speaker"
```

## What to notice
- Overrides never merge. A field you pass replaces the agent's value in full; a field you
  omit is inherited. A `model` override also replaces the agent's effort setting.
- Overrides apply to the session's own agent, not to roster subagents.
- Never call `agents.create` on every request: you would collect orphaned agents and lose
  versioning. Create once, store the ID.
