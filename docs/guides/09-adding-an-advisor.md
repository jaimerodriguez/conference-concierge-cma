# Guide 09 · Adding an advisor

**You'll learn:** how an agent on a faster model can consult a stronger model at the
moments that matter, without handing the whole task over.

The Program Chair runs on Sonnet 5.5. Before it presents an agenda, it asks an Opus 5.5
advisor about balance: variety of topics, a mix of first-time and returning speakers, and
a sensible order for the evening.

## Steps

**Step 1. Enable the advisor and pick its model.** The advisor must be at least as capable
as the agent's own model.
Find it: `managed/agents/program-chair/agent.md`, marker `Guide 09 · ... · Step 1`.

**Step 2. Tell the agent when to consult it.** Enabling the advisor only makes it
available. The system prompt carries the "when": one line under "Building the agenda".
Find it: `managed/agents/program-chair/agent.md`, marker `Step 2`.

That is the whole feature: no client code changes, and nothing to answer in the event loop.

## Try it
```sh
uv run concierge agenda build
```
In the Console session view, look for the advisor call just before the chair presents the
agenda. The CLI shows it as "[Advisor] advised the Program Chair (the advice is private)":
the advice goes only to the chair, so the event stream carries it redacted. Then remove the sentence from Step 2, apply, run again, and compare.

## What to notice
- An advisor is not a subagent. It gives advice inside the chair's own turn; it does not
  run tools or take over the task.
- You pay the stronger model's price only for the consultations, so a precise "when" in
  the prompt is what keeps the cost predictable.
- A self-hosted server does not offer the advisor. Phase 2b rewrites that sentence so the
  chair checks the balance itself (Guide 21).
