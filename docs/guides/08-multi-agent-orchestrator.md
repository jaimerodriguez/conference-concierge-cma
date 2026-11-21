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

**Step 6. See inside a workflow run.** The session's main stream is a condensed view: for
each agent a run starts it carries `session.thread_created` (with the run's
`workflow_run_id`) and the thread's status changes, plus the run's own `workflow_run.*`
events (created, phase started and ended, ended). The agents' tool calls and messages stay
on each thread's own stream. When a run thread ends (`session.thread_status_terminated`),
the loop lists that thread's events with `client.beta.sessions.threads.events.list` and
passes them on, so the live output can say what each reviewer saved.
Find it: `src/concierge/sessions.py`, marker `Step 6`.

## Try it
```sh
uv run concierge data sample                      # 8 submitted proposals, so a workflow run starts
uv run concierge review run --direct
```
The output looks like this (ids, scores and order differ from run to run):
```
[Program Chair] reading the submitted proposals
[Program Chair] starting a workflow run (Daily proposal review): Give each submitted proposal to its own reviewer in parallel and collect the outcomes.
[Workflow run] phase started: Review
[CFP Reviewer 6] started
[CFP Reviewer 1] started (2 running at once)
...
[CFP Reviewer 8] started (8 running at once)
[CFP Reviewer 5] finished, saved the review for prop_ec174438 (score 2.8, waitlist); 7 still running
...
[CFP Reviewer 6] finished, saved the review for prop_65e440d3 (score 2.4, waitlist); the last one to finish
[Program Chair] the workflow run ended: completed (8 agent threads)
[Program Chair] reading the reviewed proposals to collect the results
[Program Chair] reading the review CFP Reviewer 1 saved for prop_998b19ed
...
[Program Chair] writing digest.md
Grader, round 1 of 3: approved.
```
How to read it:
- **The chair delegates.** It lists the submitted proposals, then starts a workflow run
  and does no reviewing itself. The run starts one CFP Reviewer per proposal. The numbers
  (CFP Reviewer 1 to 8) are added by the CLI, in the order the run started them.
- **The reviews run in parallel.** All the reviewers start before the first one finishes:
  "8 running at once" is counted from the threads' status events.
- **Each reviewer reports back** by saving its review (score and recommendation) in the
  Event DB itself. A run thread has no "reply" event: its answer goes to the workflow, not
  to the chair, so the "finished" line is read from what the thread saved.
- **The chair then collects the results.** Its `get_proposal` calls after the run read the
  reviews that the reviewers saved, to write the digest. It never changes a score.
- `--verbose` adds each reviewer's own tool calls (reading the proposal and the rubrics,
  saving the review), the moment each reviewer is created, and the raw tool names.

The reviewer lines appear when each reviewer finishes, not while it works: the CLI reads a
thread's events once it has ended. To watch one reviewer's reasoning step by step, open the
session in the Console with the link the command prints at the end:
- The **timeline minimap** has one lane per thread: the chair's lane, then eight reviewer
  lanes that overlap in time. The overlap is the parallelism.
- The **Threads** tab of the inspector lists every thread with its status, context size and
  cost: one `program-chair` and one `cfp-reviewer` per proposal.
- Pick a reviewer's thread to read its transcript: the task it was given (one proposal id),
  the rubric files it read, its per-criterion scores and the `record_review` call.
- The **Events** tab shows every raw event of the thread you picked, such as the
  `workflow_run.*` and `session.thread_*` events on the chair's thread.

## What to notice
- **Workflows are on for the Program Chair in this demo.** A run starts many agents and
  every one of them uses tokens, so the sessions carry a budget (Guide 12). To turn
  workflows off, set `workflows: {type: disabled}` and apply again. The chair then
  reviews through the roster, one reviewer at a time.
- Tool calls from subagent and workflow threads that need approval are cross-posted to the
  session's main stream, so one event loop answers all of them. Calls that need no approval
  stay on the thread's own stream; that is why Step 6 reads each run thread's events.
- A roster hand-off (one to three proposals) looks different: the chair's line says
  "asking the CFP Reviewer: ...", and the reviewer's reply arrives as
  "[CFP Reviewer] reported back: ...", from the `agent.thread_message_*` events.
- Each agent keeps its own model, tools, and prompt. The reviewers record scores in the
  Event DB themselves; the chair never rewrites them.
- A self-hosted server supports the roster only, in a different shape (Guide 21).
