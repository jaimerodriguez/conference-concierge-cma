# Guide 11 · Grading work with outcomes

**You'll learn:** how to give an agent a deliverable and a rubric, and let a separate
grader send it back to work until the rubric is met.

Two places use it: the Abstract Writer (the portal's "Let AI generate abstract for me" option) and
the daily review digest.

```
 define_outcome ──► agent works ──► grader checks the rubric ──► satisfied ─► done
 (description,            ▲                    │
  rubric,                 └── needs_revision ──┘   (up to max_iterations)
  max_iterations)
```

## Steps

**Step 0. Start with a standard agent.** Check `managed/agents/abstract-writer/agent.md`.

**Step 1. Start the session with an outcome instead of a message.** The
`user.define_outcome` event carries the description, the rubric, and `max_iterations`.
Find it: `src/concierge/abstracts.py`, marker `Guide 11 · ... · Step 1`.

**Step 2. Write the rubric as checkable statements.** The digest rubric sits next to the
schedule that uses it. "Has a table with one row per proposal" can be graded; "is good"
cannot.
Find it: `managed/deployments/daily-review.yaml`, marker `Step 2`.
The abstract rubric is a file: `content/rubrics/abstract.md`.

**Step 3. Read the grader's verdict from the stream.** `span.outcome_evaluation_end` carries
the result (`satisfied`, `needs_revision`, `max_iterations_reached`, and so on) and an
explanation.
Find it: `src/concierge/sessions.py`, marker `Step 3`.

**Step 4. Fetch the deliverable.** The agent writes to `/mnt/session/outputs/`, and the
client downloads the file by session.
Find it: `src/concierge/abstracts.py`, marker `Step 4`.

## Try it
```sh
uv run concierge propose "Building AI agents"     # the Abstract Writer writes the abstract
uv run concierge review run --direct     # prints "Grader, round 1 of 3: ..." lines as it iterates
```

## What to notice
- The grader sees only the rubric and the work, so give it ground truth: the daily review records its
  **start state** (which proposals were submitted) on the first line of the digest, and the rubric
  judges against that. Without it the grader guesses from timestamps and can contradict itself
  between rounds.
- The grader is separate from the agent and sees only the rubric and the work, which is
  what makes its verdict worth reading.
- `max_iterations` and the session budget together bound the cost of "until it's right".
- The rubrics here are starters. Tune them against a few real runs before you rely on them.
- Output files appear a moment after the session goes idle, so `read_output_file` retries
  briefly. Where there is no Files API (Guide 21), the demo falls back to the agent's reply.
