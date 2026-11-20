# Guide 08 · Configuring your orchestrator for multi-agent

**You'll learn:** how one coordinator agent (the Program Chair) hands work to a roster of
specialists, and how it can fan work out with a dynamic workflow.

```
                         Program Chair (coordinator)
            ┌───────────────────┼─────────────────────┐
     roster: delegate      roster: delegate      workflow run (background)
            ▼                   ▼                 ┌──────┼──────┐
      scheduler          speaker-liaison      reviewer reviewer reviewer
                                              (one cfp-reviewer per proposal)
```

Two ways to delegate, both configured in one block:

| | Roster (`subagents`) | Dynamic workflow (`workflows`) |
|---|---|---|
| Who plans | The coordinator, one hand-off at a time | The coordinator writes a script that runs many agents in phases |
| Good for | A well-scoped task for one specialist | The same task over many items, in parallel |
| In this demo | Scheduling, perk codes, one to three reviews | Reviewing more than three proposals |

## Steps

**Step 1. Add the `multiagent` block to the coordinator.**
Find it: `managed/agents/program-chair/agent.md`, marker `Guide 08 · ... · Step 1`.

**Step 2. List the roster.** Agents are referenced by file path, so `ant apply` creates
them first and fills in their IDs. `inline_agents` is disabled: the chair may use only the
agents listed.
Find it: `managed/agents/program-chair/agent.md`, marker `Step 2`.

**Step 3. Turn on dynamic workflows** and say which agents a workflow may use. The system
prompt in the same file says *when* to start one ("more than three proposals") and what to
do when a reviewer fails.
Find it: `managed/agents/program-chair/agent.md`, marker `Step 3`.

**Step 4. Start a session for the coordinator only.** The session names one agent. It
still needs everything the *subagents* will use: the vault and the memory stores.
Find it: `src/concierge/review.py`, marker `Step 4`.

**Step 5. Follow workflow runs in the event loop.** A run keeps going in the background
after the coordinator's turn ends, so "idle" does not always mean "done". The loop tracks
`workflow_run.created` and `workflow_run.status_ended` and waits for open runs.
Find it: `src/concierge/sessions.py`, marker `Step 5`.

## Try it
```sh
uv run concierge data sample                      # 8 submitted proposals, so a workflow run starts
uv run concierge review run --direct
```
Open the Console link that the command prints. Each subagent and each workflow agent has
its own thread, and the cost is shown per session.

## What to notice
- **Workflows are on for the Program Chair in this demo.** A run starts many agents and
  every one of them uses tokens, so the sessions carry a budget (Guide 12). To turn
  workflows off, set `workflows: {type: disabled}` and apply again. The chair then
  reviews through the roster, one reviewer at a time.
- Tool calls from subagent and workflow threads that need approval are cross-posted to the
  session's main stream, so one event loop answers all of them.
- Each agent keeps its own model, tools, and prompt. The reviewers record scores in the
  Event DB themselves; the chair never rewrites them.
- A self-hosted server supports the roster only, in a different shape (Guide 21).
