# Guide 13 · Moderating user input

**You'll learn:** how to screen what the audience types before any agent sees it, with one
plain Messages API call. Not everything needs an agent.

The proposal form lets people type their own topic. The house rule is simple: nothing
sexual or violent.

## Steps

**Step 1. Screen typed input first.** Predefined topics skip the check; typed ones do not.
Find it: `src/concierge/proposals.py`, marker `Guide 13 · ... · Step 1`.

**Step 2. Make one call with structured output.** The answer is parsed into a small
Pydantic model (`ModerationVerdict`), so the code branches on a field instead of reading
prose.
Find it: `src/concierge/moderation.py`, marker `Step 2`.

**Step 3. Fail closed.** A refusal, or an answer that cannot be parsed, rejects the topic.
Find it: `src/concierge/moderation.py`, marker `Step 3`.

## Try it
```sh
uv run concierge propose "a topic you typed" --name Sam
```
Or use the portal at your tunnel address from a phone.

To fill the queue for a demo, `uv run concierge data sample --generate` sends several
proposals down this same path. Its topics are the predefined ones, so they skip the check
by design. Without `--generate` the samples are written offline, at no cost.

## What to notice
- This is the cheapest tier that does the job: a single call on Haiku 5.5, no session, no
  sandbox, no tools.
- The check runs in your own process, so it works the same in phase 1 and phase 2.
- The person sees a friendly "please pick another topic" and never the model's reasoning.
- The Abstract Writer's rubric repeats the house rule, so generated text is held to it too.
