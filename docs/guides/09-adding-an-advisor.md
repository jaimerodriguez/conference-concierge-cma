# Guide 09 · Adding an advisor

**You'll learn:** how an agent on a faster model can consult a stronger model at the
moments that matter, without handing the whole task over.

The Program Chair runs on Sonnet 5.5. Before it asks the Scheduler to book anything, it
asks an Opus 5.5 advisor about the proposals it means to accept and their running order:
variety of topics, a mix of first-time and returning speakers, and a sensible order for the
evening. Because the advice comes before booking, it can still change the plan.

## Steps

**Step 1. Enable the advisor and pick its model.** The advisor must be at least as capable
as the agent's own model.
Find it: `managed/agents/program-chair/agent.md`, marker `Guide 09 · ... · Step 1`.

**Step 2. Tell the agent when to consult it.** Enabling the advisor only makes it
available. The system prompt carries the "when": one line under "Building the agenda".
Find it: `managed/agents/program-chair/agent.md`, marker `Step 2`.

That is the whole feature: no client code, and nothing to answer in the event loop. Step 3
only makes the consultation visible in the CLI.

**Step 3. See the consultation.** The advice never reaches your client in plain text, but
the consultation leaves a record you can read. When the advisor's thread ends
(`session.thread_status_terminated` with `agent_name` `anthropic.advisor`), the loop reads
that thread with `client.beta.sessions.threads.retrieve` and passes its model, duration,
tokens and cost to the live output.
Find it: `src/concierge/sessions.py`, marker `Step 3`.

## How a consultation works
1. **The chair decides when.** Nothing in the client starts it. The chair's model chooses
   to consult, at the point its prompt names ("before you ask the scheduler to book").
2. **The platform sends the context, not a question.** The chair only signals "consult now".
   The advisor receives the chair's whole conversation so far: its system prompt, the
   tools, the organizer's request, the proposals and the fit check it has read so far. The chair
   writes no separate question, so there is no request event to show.
3. **The advisor answers once and stops.** It runs on its own thread, on its own model,
   without tools. Its advice goes back to the chair, inside the chair's turn, and the
   advisor's thread ends.
4. **Only the chair can read the advice.** With an Opus 5.5 advisor, the advice is
   encrypted for the agent it advises. Every event that carries it (on the chair's stream
   and on the advisor's own thread) shows the content as `{"type": "redacted"}`. The chair
   reads it server-side; your client cannot.
5. **The chair carries on.** It takes the advice into account and continues its turn: it
   accepts the proposals and hands the Scheduler a running order. You see the result in the
   chair's next steps and in the order of the bookings, but nothing marks which parts came
   from the advisor.

## Try it
```sh
uv run concierge agenda build
```
The output looks like this (wording, timing and cost differ from run to run):
```
[Program Chair] checking whether 4 more proposals fit in the evening
[Program Chair] looking up members
[Program Chair] consulting its advisor, which reads the whole conversation so far and replies with advice
[Advisor] advised the Program Chair (Opus 5.5, 14 s, $0.04). The advice goes only to the Program Chair; this client gets it encrypted.
[Program Chair] marking prop_f9aca07a as accepted
[Program Chair] marking prop_352e846a as accepted
…
[Program Chair] asking the Scheduler: Please plan agenda slots and book them on the organizer's calendar for the AI Me…
```
How to read it:
- **When:** the "consulting its advisor" line comes from `session.thread_created` for a
  thread named `anthropic.advisor`. Its place in the output is the point in the chair's
  turn where it consulted: after the fit check and before any proposal is accepted or
  booked, so the advice can still change which proposals are accepted and in what order.
- **Which model and what it cost:** the "advised" line comes from the advisor thread's
  record (`agent.model`, `stats.duration_seconds`, `usage.list_cost`), read when the
  thread ends. The cost is the advisor's alone, at Opus rates; it is part of the session
  cost in the summary at the end.
- **What the advice said:** not shown, because the client receives it encrypted.
- `--verbose` adds the token counts, for example "read 11,446 tokens of the Program
  Chair's conversation and wrote 1,908 tokens of advice". The large read is the chair's
  whole conversation: that is the context the platform sent. It also shows the redacted
  `agent.thread_message_received` event the advice arrived in.

To compare, remove the sentence from Step 2, apply, and run again: the two advisor lines
disappear, and so does the advisor's cost.

### In the Console
Open the session with the link the command prints at the end. What follows is from the
[session observability docs](https://platform.claude.com/docs/en/managed-agents/session-observability);
those docs do not describe advisor threads specifically, so check it on screen:
- The **timeline minimap** has one lane per thread. The advisor's thread should be a short
  lane that starts and ends inside the chair's turn.
- The **Threads** tab lists every thread with its status, context size and cost. The
  advisor's row is where its own cost shows next to the chair's.
- The **Events** tab shows the raw events, including the redacted advice. Expect the
  advice text to be withheld there too.

## What to notice
- **The "when" decides what the advice can change.** "Before you ask the scheduler to book"
  puts the advice where it can still shape the plan: which proposals are accepted and the
  running order the Scheduler books. An earlier version said "before you present a final
  agenda"; the advisor then spoke after every slot was booked, and its advice could change
  only what the chair told the organizer.
- An advisor is not a subagent. It gives advice inside the chair's own turn; it does not
  run tools or take over the task.
- You pay the stronger model's price only for the consultations, so a precise "when" in
  the prompt is what keeps the cost predictable.
- A self-hosted server does not offer the advisor. Phase 2b rewrites that sentence so the
  chair checks the balance itself, still before booking (Guide 21).
