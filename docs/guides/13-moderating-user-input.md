# Guide 13 · Moderating user input

**You'll learn:** how to screen what the audience types before any agent sees it, with one
plain Messages API call. Not everything needs an agent.

The proposal form asks for a talk title, and optionally an abstract the person writes
themselves. The house rule is simple: nothing sexual or violent.

## Steps

**Step 1. Screen typed input first.** The title is checked before the Abstract Writer
sees it. A hand-written title and abstract are checked together instead
(`moderate_abstract`, same model, same answer shape, its own prompt).
Find it: `src/concierge/proposals.py`, marker `Guide 13 · ... · Step 1`.

**Step 2. Make one call with structured output.** The answer is parsed into a small
Pydantic model (`ModerationVerdict`), so the code branches on a field instead of reading
prose.
Find it: `src/concierge/moderation.py`, marker `Step 2`.

**Step 3. Fail closed.** A refusal, or an answer that cannot be parsed, rejects the input.
Find it: `src/concierge/moderation.py`, marker `Step 3`.

## Try it
```sh
uv run concierge propose "a title you typed" --email sam@example.com
uv run concierge propose "a title you typed" --abstract "The abstract you wrote, 50 characters or more."
```
The first lets the Abstract Writer draft the abstract, so only the title is screened before the
session starts. The second is your own abstract (`--abstract-file` reads it from a file, or
from stdin with `-`): title and abstract are screened together, and no agent session runs.
The portal at your tunnel address offers the same choice: uncheck "Let AI generate abstract
for me" to write your own. Both run the same free checks first (email, lengths, track,
persona) and the same moderation.

To fill the queue for a demo, `uv run concierge data sample --generate` sends the sample
proposals down this same path, check included. The five accurate ones get their abstract from
the Abstract Writer. The problem cases keep their own abstracts, so they are screened the way
a typed abstract is: watch moderation stop the inappropriate one and the prompt injection
before they are saved. The others (a mismatched title, a sales pitch, a workshop in a
lightning slot) get through, because moderation does not judge quality; the CFP Reviewers
catch those.

Without `--generate` the samples are saved as written, at no cost, and moderation never sees
them. That shows the second line of defense: the inappropriate proposal reaches the review,
the "Respectful" criterion declines it, and the digest names it.

## What to notice
- This is the cheapest tier that does the job: a single call on Haiku 5.5, no session, no
  sandbox, no tools.
- The check runs in your own process, so it works the same in phase 1 and phase 2.
- The person sees a friendly "please try something else" and never the model's reasoning.
  A rejection ends with a statement such as "You could resubmit with a title like: …", not a
  question: the CLI and the portal answer once, so there is nobody to reply to.
- The Abstract Writer's rubric repeats the house rule, so generated text is held to it too.
