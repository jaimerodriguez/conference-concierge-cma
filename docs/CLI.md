# Command reference

Every `concierge` command and option. This file is generated from the code
(`uv run python -m concierge.cli_reference`) and a test fails if it is out of date, so it
always matches what the program accepts.

Ask the program itself at any level, for example:

```sh
uv run concierge --help
uv run concierge setup --help
uv run concierge setup vault --help
```

Run everything with `uv run` from the repo root (or from anywhere inside the repo).
Options with a default can be left out. `--install-completion` and `--show-completion`
(shell tab-completion) exist on the top-level command only.

## `concierge serve`

Run the mock services (OAuth, Calendar MCP, Event DB MCP, CloudCredits) and the portal.

```sh
uv run concierge serve [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Interface to listen on. |
| `--port` | `8000` | Port to listen on (your tunnel points here). |
| `--portal / --no-portal` | on | Also serve the proposal form at /. |

## `concierge propose`

Submit a proposal from the terminal (the portal does the same from a phone).

```sh
uv run concierge propose TITLE [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `TITLE` | required | The talk's title. The agent writes the abstract. |
| `--email` | `sam@example.com` | Member's contact email. |
| `--persona` | `weekend-hacker` | Speaker persona id from content/personas.yaml. |
| `--track` | `fun` | Track id from content/tracks.yaml. |

## `concierge proposals`

List proposals in the local Event DB.

```sh
uv run concierge proposals [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--status` | none | Only show proposals with this status (submitted, reviewed, accepted, waitlisted, declined). |

## `concierge ask`

Ask the Attendee Helper a question about the event or venue.

```sh
uv run concierge ask QUESTION [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `QUESTION` | required | Your question, in quotes. |
| `--verbose` | off | Also show the raw tool names in the live output. |

## `concierge bio`

Write a speaker bio with an agent created at runtime (Guide 03).

```sh
uv run concierge bio NAME FACTS [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `NAME` | required | The speaker's name. |
| `FACTS` | required | Facts to work into the bio, in quotes. |
| `--verbose` | off | Also show the raw tool names in the live output. |

## `concierge doctor`

Check the local setup, that every server URL agrees, and say what to do next.

```sh
uv run concierge doctor [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--offline / --no-offline` | off | Skip the checks that ask the Claude API what is stored. |

## `concierge setup host`

Write your public tunnel host into the files under managed/.

```sh
uv run concierge setup host [HOSTNAME]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `HOSTNAME (optional)` | none | Defaults to the host in CONCIERGE_PUBLIC_BASE_URL (.env). |

## `concierge setup public`

Put the sample host and an empty vault list back, so the files are safe to publish.

```sh
uv run concierge setup public [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--check` | off | Only list the files that hold your values; change nothing. |

## `concierge setup all`

Run the whole phase 1 setup in order; safe to re-run, stops at the first failure.

```sh
uv run concierge setup all [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--yes` | off | Pass --yes to `ant apply` (do not ask before applying). |
| `--browser / --no-browser` | on | Open the Calendar sign-in page automatically. |
| `--reauth-calendar / --no-reauth-calendar` | off | Sign in to the Calendar again even if the vault has a token. |

## `concierge setup show`

Show the IDs `ant apply` recorded, including the vault ID the deployment file needs.

```sh
uv run concierge setup show
```

## `concierge setup deployment`

Put the applied vault's ID into the daily-review deployment file (Guide 10, Step 2).

```sh
uv run concierge setup deployment
```

## `concierge setup memory`

Seed the memory stores from content/ (venues, rubrics, ops notes). Safe to re-run.

```sh
uv run concierge setup memory
```

## `concierge setup vault`

Store the Event DB token and the CloudCredits API key in the vault.

```sh
uv run concierge setup vault [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--remove-stale` | off | Delete vault credentials stored for addresses this app no longer uses. |
| `--yes` | off | Do not ask before deleting. |

## `concierge auth calendar`

Sign in as the organizer and store the Calendar OAuth tokens in the vault.

```sh
uv run concierge auth calendar [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--browser / --no-browser` | on | Open the sign-in page automatically. |

## `concierge review run`

Run the daily proposal review now and follow it, reviewer by reviewer.

```sh
uv run concierge review run [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--direct / --no-direct` | off | Start an ordinary session instead of firing the deployment. |
| `--force / --no-force` | off | Start the review even when no proposal is waiting. |
| `--verbose` | off | Also show each reviewer's own tool calls and the raw tool names. |

## `concierge review runs`

Show recent firings of the scheduled review, including failed ones.

```sh
uv run concierge review runs [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--limit` | `10` | How many recent runs to show. |

## `concierge agenda build`

Ask the Program Chair to build the agenda. You approve each calendar booking.

```sh
uv run concierge agenda build [INSTRUCTION] [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `INSTRUCTION (optional)` | none | What to ask the Program Chair. Default: accept the top four, breaking ties for variety, then book. With --session: your reply, or leave it out to re-attach and answer what is waiting. |
| `--session` | none | Continue this agenda session (sesn_...): answer any booking still waiting for approval, then follow it. |
| `--verbose` | off | Also show the advisor's token counts and the raw tool names. |

## `concierge data clear`

Delete the demo data from runs so the demo starts clean. Permanent.

```sh
uv run concierge data clear [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--yes` | off | Delete without asking. |
| `--local-only` | off | Only clear the local Event DB; leave the ops-notes memory alone. |

## `concierge data sample`

Add sample talk proposals, status "submitted", so `review run` has work.

```sh
uv run concierge data sample [OPTIONS]
```

| Argument or option | Default | What it does |
| --- | --- | --- |
| `--count` | `8` | How many proposals to create. |
| `--seed` | none | Seed for the random picks (offline mode), to repeat a set. |
| `--generate / --no-generate` | off | Have the Abstract Writer write each abstract (the `propose` path). Costs about a cent each. |
| `--yes` | off | With --generate: do not ask first. |
