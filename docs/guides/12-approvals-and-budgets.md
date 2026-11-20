# Guide 12 · Approvals and budgets

**You'll learn:** two guardrails that work together. Permission policies decide *which tool
calls wait for a person*, and budgets decide *how much a session may spend*.

In the demo the Scheduler may read the calendar freely, but booking a slot waits for the
organizer. So does each sponsor perk code the Speaker Liaison issues.

## Steps

**Step 1. Set permission policies per tool.** The Calendar toolset defaults to
`always_ask`; the two read-only tools are set to `always_allow`.
Find it: `managed/agents/scheduler/agent.md`, marker `Guide 12 · ... · Step 1`.

| Policy | Meaning |
|---|---|
| `always_allow` | Runs without asking |
| `always_ask` | Pauses until your client answers. The default for MCP toolsets |
| `auto` | A classifier decides whether a call needs a person |

**Step 2. Give every session a budget.** The amount is in cents, as a string: `"50"` is
$0.50. At the cap the session pauses with `budget_reached`; it is not terminated.
Find it: `src/concierge/sessions.py`, marker `Step 2`, and in use in
`src/concierge/abstracts.py`, marker `Step 2`.

**Step 3. Put a budget on the deployment too.** It is copied onto each session the
schedule fires.
Find it: `managed/deployments/daily-review.yaml`, marker `Step 3`.

**Step 4. Answer paused calls in the event loop.** A call that needs a decision arrives
with `evaluated_permission == "ask"`. The client replies with `user.tool_confirmation`,
and a denial can carry a message so the agent can adjust.
Find it: `src/concierge/sessions.py`, marker `Step 4`.

**Step 5. Put the decision in front of a person.** The CLI asks one plain question per
call, such as "Book 'Break' in Main Hall, 19:20-19:30?". Answer `y`, `n` (it then asks why,
and the agent reads your reason), or `a` to approve this and every remaining booking in the
run. `--verbose` also shows the tool name and its raw input. Where nobody is watching, the
default approver denies everything.
Find it: `src/concierge/cli.py`, marker `Step 5`.

Perk codes work the same way. Issuing one spends sponsor money, so the Speaker Liaison's
`bash` tool is set to `always_ask` (`managed/agents/speaker-liaison/agent.md`), and it makes
one request per code. Each call arrives as "Issue a CloudCredits perk code ($50) for Priya
(mem_...)?". Here `a` approves the remaining perk codes only, never other shell commands.

## Try it
```sh
uv run concierge agenda build
```
Decline one booking and give a reason, such as "not before 6:30 PM". The Scheduler reads
your reason and proposes another slot.

While the agents work, each step is one line. When the Program Chair ends its turn, its
last message is shown in full, then the CLI asks for your reply. Type one to carry on in
the same session, or press Enter to finish. The default instruction tells the chair how to
break ties (variety of tracks and speakers), so it should not stop to ask. If it does stop,
and you finished without answering, reply later in that session:
```sh
uv run concierge agenda build --session sesn_... "Accept prop_... and prop_..."
```

Take your time at an approval prompt. If the event stream closes while you think, the CLI
reopens it and catches up from the session's history. If the CLI itself was closed, re-attach
with no reply text: it asks about any booking still waiting, then keeps following.
```sh
uv run concierge agenda build --session sesn_...
```
The run ends with a summary: events on the calendar, bookings requested in this run, perk
codes issued, and the session's cost so far.

## What to notice
- The confirmation's `tool_use_id` is the ID of the *event*, not of a tool call inside it.
- Approval requests from subagents and workflow agents arrive on the same stream.
- A reply is just another `user.message` sent to the same session, so the chair keeps
  everything it already read and decided.
- A session waits for an approval as long as it takes; only the stream closes. Re-attaching
  reads the history, skips calls that already have a `user.tool_confirmation`, and asks
  about the rest (`follow_session(..., attach=True)` in `sessions.py`).
- "Deny by default" is the safe choice for unattended runs: `deny_all` in `sessions.py`.
- Budgets matter most where workflows are on, since one run starts many agents (Guide 08).
