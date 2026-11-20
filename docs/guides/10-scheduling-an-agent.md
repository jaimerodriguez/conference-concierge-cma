# Guide 10 · Scheduling an agent

**You'll learn:** how to have an agent run on a schedule with nobody attached. Here, the
Program Chair reviews new proposals every morning at 8:00.

A **deployment** is a stored recipe for a session: the agent, the environment, vaults,
resources, a budget, the first events, and a schedule. Each firing creates a new session.

## Steps

**Step 1. Declare the deployment.**
Find it: `managed/deployments/daily-review.yaml`, marker `Guide 10 · ... · Step 1`.

**Step 2. Give it the vault by ID.** Agents and environments can be referenced by path,
but `vault_ids` takes IDs. Apply once to create the vault, let `concierge` write its ID into the
file, and apply again. **Skip this and every fired session has no vault**, so its MCP servers fail
with "no credential is stored for this server URL":

```sh
cd managed && ant apply --yes && cd ..
uv run concierge setup deployment      # writes the vlt_... ID into vault_ids
cd managed && ant apply --yes && cd ..
```
Find it: `managed/deployments/daily-review.yaml`, marker `Step 2`.

**Step 3. Set the schedule.** A cron expression in wall-clock time, with an IANA timezone.
Find it: `managed/deployments/daily-review.yaml`, marker `Step 3`.

**Step 4. Fire it by hand.** A manual run creates a session immediately with the
deployment's exact configuration. This is how you test a schedule, and how you trigger the
review on stage.
Find it: `src/concierge/review.py`, marker `Step 4`.

**Step 5. Follow the session it created.** A deployment run is an ordinary session. The
loop reads the history first, because the session started before we attached.
Find it: `src/concierge/review.py`, marker `Step 5`.

## Try it
```sh
uv run concierge review run       # fires the deployment now and follows it
uv run concierge review runs      # recent firings, including failed ones
```
With no proposal waiting, `review run` starts nothing (a review costs money): add some with
`uv run concierge data sample`, or pass `--force` to fire it on an empty queue.

## What to notice
- **Nobody is there to approve.** Every tool the scheduled run needs must run without
  asking. That is why the Event DB toolset is `always_allow` on the chair and the reviewer.
  A tool left on `always_ask` would leave the session waiting.
- The kickoff is an outcome with a rubric, not a chat message (Guide 11), and the budget
  on the deployment is copied onto every session it fires (Guide 12).
- `concierge review run --direct` runs the same review as a plain session. That is the
  path a cron job uses where deployments do not exist (Guide 21).
- A firing can fail before a session exists, for example when a resource was deleted.
  `review runs` shows those too.
