# Conference Concierge: specification

A public, educational demo of **Claude Managed Agents**, shared as source code at a user group.
A small team of agents runs a user-group meetup: they help people propose talks, review the
proposals against track rubrics, build the agenda, book calendar slots, issue sponsor perks to
accepted speakers, and answer attendee questions about the venue.

Status: v1.1 (2026-11-19). The organizer confirmed the member model, the additional features,
the 2a/2b split, and the event name on 2026-11-19.

---

## 1. Goals

1. Show every feature on the phase 1 list in one coherent, fun, real-world scenario.
2. Ship as readable Python source that attendees can clone and run against their own Claude
   API workspace.
3. Teach through **task guides**: short how-tos that point into the source. Code carries
   `Step N of <guide>` comments, so a reader can jump from a guide to the code and back.
4. Phase 2 shows what changes, and what you deliberately give up, when you self-host the
   sandbox and then the whole service.

Non-goals: a production event platform, real email delivery, a real calendar provider.

---

## 2. The story

The "AI Meetup" runs a monthly event. Before each event:

1. **Members propose talks.** Anyone at the event can open the portal on their phone, enter a
   contact email and a talk title, and either let an agent write the abstract (in the voice of
   a persona they pick) or write their own. They also pick a track. The proposal board groups
   every proposal as Accepted, Reviewed, Not this time, or Awaiting review.
2. **Every morning, the Program Chair reviews new proposals.** A scheduled run fans out the
   new proposals to CFP Reviewers, who score each against the base rubric plus its track
   rubric. The chair writes a digest.
3. **The organizer accepts talks and the chair builds the agenda.** The chair checks that the
   talks fit in the evening (accepting only those that do), consults its advisor about topic
   and speaker balance before anything is booked, then delegates slot planning to the
   Scheduler, which pauses for the organizer's approval before booking calendar slots.
4. **Accepted speakers get a perk.** The Speaker Liaison issues each accepted speaker a
   "CloudCredits" sponsor code through an API whose key lives in a vault.
5. **Attendees ask questions.** The Attendee Helper answers "Where do I park?" or "Is there
   vegan food?" from the venue profile, and the operations team's notes.

Live demo hook: the audience submits talks from their phones during the presentation, and
the presenter triggers the daily review on stage.

---

## 3. Domain model

### 3.1 Members and roles

One **member** profile with roles, not separate attendee and speaker entities.

- Everyone who RSVPs is a member with the `attendee` role.
- Submitting a proposal makes them a `submitter`.
- An accepted proposal adds the `speaker` role, which triggers the perk code and a calendar slot.

This gives the demo its arc: an audience member becomes a speaker, live.

### 3.2 Proposals

| Field | Notes |
|---|---|
| `id`, `member_id`, `event_id` | |
| `track` | One of the configured tracks (§3.3) |
| `title`, `abstract`, `format` | `format`: talk (25 min) or lightning (5 min) |
| `source` | `ai_abstract` (the Abstract Writer wrote it), `manual_abstract` (the person did), or `sample` |
| `status` | `submitted` → `reviewed` → `accepted` / `waitlisted` / `declined` |
| `scores` | Per-criterion scores written by the CFP Reviewer |

### 3.3 Tracks and templated rubrics

A rubric is a **shared base plus a per-track add-on**, both markdown files in
`content/rubrics/`:

| File | Criteria |
|---|---|
| `base.md` | Clarity (title and abstract describe the same talk), originality, fits the time slot, audience takeaway, abstract length, respectful |
| `tracks/ai-ml.md` | Technical depth, demo or evidence, reproducibility |
| `tracks/community.md` | Inclusiveness, actionable for organizers, story |
| `tracks/lightning.md` | One idea, fits 5 minutes, memorable hook |
| `tracks/fun.md` | Delight, audience participation, still teaches something |

Adding a track means adding one markdown file. Rubrics are used twice:

1. **Proposal scoring.** The CFP Reviewer reads base + track rubrics and scores each criterion.
2. **Abstract quality (Outcomes).** The Abstract Writer's session is graded against the track
   template, so a generated abstract iterates until it meets the format (§5.3).

### 3.4 Venues

Each venue is a markdown profile in `content/venues/` (address, parking, transit, wifi,
accessibility, food, rooms, AV). An event points at one venue. Two sample venues ship so the
demo can show switching venues: a tech office and a public library.

### 3.5 Personas and sample proposals

`content/personas.yaml` holds the portal's personas ("Weekend hacker", "Data engineer",
"Community organizer"…). `content/sample_proposals.yaml` holds the AI-centered proposals
`concierge data sample` adds: five solid ones and five problem cases the review should catch
(a title that does not match its abstract, inappropriate content, a prompt injection, a sales
pitch, a workshop in a lightning slot), ten at most. The portal does not offer topics: the
person's title is what the agent writes about.

---

## 4. Architecture

```
                 ┌───────────────────────────── Anthropic (Managed Agents) ─────────────────────────────┐
 Phone ──► Portal│  Abstract Writer (on-the-fly)     Program Chair ──advisor──► Opus                     │
 (FastAPI)  │    │                                   │  roster: CFP Reviewer, Scheduler, Speaker Liaison │
            │    │  Attendee Helper                  │  workflow runs: CFP Reviewer × N                 │
 Moderator  │    │                                   │                                                  │
 (Messages  │    │  Memory stores: venues (ro), rubrics (ro), ops-notes (rw)                            │
  API call) │    │  Vault: calendar OAuth, event-db bearer, CloudCredits key (env var)                  │
            │    │  Deployment: daily review, 08:00 local                                               │
            │    └──────────────┬───────────────────────────────────────────────────────────────────────┘
            │                   │ MCP (HTTPS)        │ HTTPS (secret injected at egress)
            ▼                   ▼                    ▼
       concierge-services (one Starlette app, public via a tunnel)
         /oauth/*      tiny OAuth 2.0 authorization server (auth code + PKCE + refresh)
         /calendar/mcp Calendar MCP server (requires OAuth bearer)
         /eventdb/mcp  Event DB MCP server (members, proposals, scores, rooms; static bearer)
         /credits/api  CloudCredits sponsor API (API key header)
         SQLite storage

 Local: Jaeger, which accepts OTLP directly (docker compose); `concierge` CLI (Typer).
```

Why one services app: a single public tunnel URL (for example `cloudflared` or `ngrok`) keeps the
demo setup to one command. Anthropic's MCP proxy and the sandbox must reach these services over
public HTTPS, which is why the tunnel is required. In code, each service is its own module.

### 4.1 Agents

All agents are declared as files under `managed/agents/` and synced with `ant apply`, except
where noted.

| Agent | Model | Declared | Role | Tools |
|---|---|---|---|---|
| **Program Chair** | Sonnet 5.5, advisor Opus 5.5 | ant | Coordinator. Runs the daily review, builds the agenda, delegates | agent toolset; Event DB MCP (read); multiagent roster + workflows + advisor |
| **CFP Reviewer** | Sonnet 5.5 | ant | Scores one or more proposals against base + track rubric | Event DB MCP (read proposals, write scores); rubrics memory |
| **Scheduler** | Sonnet 5.5 | ant | Plans slots, books calendar events as the organizer | Calendar MCP (OAuth, `always_ask` on create); Event DB MCP |
| **Speaker Liaison** | Haiku 5.5 | ant | Issues CloudCredits perk codes, drafts welcome notes | bash (curl with vault env var); Event DB MCP |
| **Attendee Helper** | Haiku 5.5 | ant | Answers attendee questions | venues memory (read-only), ops-notes (read-only) |
| **Abstract Writer** | Haiku 5.5 base | ant (base) + **on-the-fly overrides** per request | Writes an abstract for the person's title, persona, and track | agent toolset (write only) |
| **Speaker Bio Writer** | Haiku 5.5 | **created at runtime** with `agents.create` (guarded, created once) | Writes a short bio for an accepted speaker | none beyond write |
| **Moderator** | Haiku 5.5 | *Not an agent.* One Messages API call with structured output | Allows or rejects a typed title, or a title and abstract | n/a |

The Moderator is deliberately a single API call: a teaching point that not every step needs an
agent.

### 4.2 MCP servers and credentials

| Service | Auth | Vault credential type | Why |
|---|---|---|---|
| Calendar MCP | OAuth 2.0, organizer signs in | `mcp_oauth` with refresh | Phase 1 item 7: the client runs the OAuth flow, stores tokens in a vault, attaches it to the session; Anthropic refreshes them |
| Event DB MCP | Static bearer token | `static_bearer` | Contrast with OAuth; also what phase 2b falls back to |
| CloudCredits API | API key header | `environment_variable` (`CLOUDCREDITS_API_KEY`, header only, limited to the services host) | The sandbox sees only a placeholder; print `$CLOUDCREDITS_API_KEY` on stage to prove it |

### 4.3 Memory (system-level, not per-user)

Memory stores are workspace-scoped, which matches "memory specific to the system":

| Store | Access | Contents | Written by |
|---|---|---|---|
| `venues` | read-only for agents | One file per venue profile, seeded from `content/venues/` | Seed script |
| `rubrics` | read-only | `base.md` + `tracks/*.md` | Seed script |
| `ops-notes` | read-write for Chair and Scheduler, read-only for Attendee Helper | What agents learn: "Room B projector needs HDMI", "Talks run 10 minutes over" | Agents |

No store is per member. Attendee input never writes to memory (the Attendee Helper's access is
read-only), which also blocks memory poisoning from the public.

---

## 5. Feature coverage (phase 1, hosted)

| # | Feature | Where it shows up |
|---|---|---|
| 1a | Agents declared with `ant` CLI | `managed/agents/*/agent.md`, `ant apply`, `claude-lock.json` |
| 1b | On-the-fly agent | Abstract Writer via `agent_with_overrides` (per-request system prompt from persona + track); Speaker Bio Writer via runtime `agents.create` |
| 2 | Vaults | Calendar `mcp_oauth`, Event DB `static_bearer`, CloudCredits `environment_variable` |
| 3 | System-level memory | Three workspace-scoped stores (§4.3) |
| 4 | OpenTelemetry | SDK tracing in the CLI and portal to Jaeger; API tracing destination (guide only, needs an org admin) |
| 5 | Scheduling | Deployment `daily-review`, 08:00 local, plus `deployments.run` to fire it on stage |
| 6a | Multi-agent: advisor | Program Chair consults Opus 5.5 before the agenda is booked |
| 6b | Multi-agent: workflow | Program Chair starts a dynamic workflow run that reviews N proposals in parallel with CFP Reviewers; plus the fixed roster for delegation |
| 7 | MCP with OAuth from the client | `concierge auth calendar` runs the OAuth sign-in and stores tokens in the vault |

### 5.1 Additional features

| Feature | Where | Why include |
|---|---|---|
| **Outcomes** | Abstract Writer (graded against the track template); daily digest (graded against a digest rubric) | Rubric-graded iteration fits the scenario |
| **Permission policies** | Calendar event creation and the Speaker Liaison's perk-code calls (`bash`) are `always_ask`; organizer approves in the CLI | Human-in-the-loop |
| **Session budgets** | Every session the portal creates gets a $0.50 cap; daily review $5 | Safe for a public demo taking audience input |
| **Agent versioning** | Edit a prompt, `ant apply`, show the new version and pinned sessions | Shows the create-once, version-in-place model |
| Console session viewer, `ant beta:sessions connect` | Debugging tips in guides | Zero-setup observability |

### 5.2 Safety for audience input

1. Personas and tracks are picked from lists, so they need no check.
2. Every typed title goes to the Moderator (Haiku 5.5, structured output: `allowed`, `reason`,
   `suggestion`). Rejects sexual, violent, hateful or harassing content, real private people,
   and anything not respectful. Rejection shows a friendly "try something else" with a suggestion,
   phrased as a statement ("You could resubmit with a title like: …"), never a question.
   A title and abstract a person writes themselves go through the same check, with the same
   house rule, before they are saved.
3. The Abstract Writer's prompt repeats the content rules (defense in depth).
4. Session budgets cap spend per submission; the portal rate-limits per IP.

### 5.3 Key flows

**Propose a talk (on-the-fly agent + outcome).**
Portal → moderation of the title → `sessions.create` with `agent_with_overrides` (system prompt
built from persona + track, `budget`) and `initial_events: [user.define_outcome]` whose rubric is
base + track template → stream until idle → read `abstract.json` from the session → save the
proposal through the services API. When the person writes their own abstract, the portal
moderates the title and abstract and saves them as they are (source `manual_abstract`); no
session runs.

**Daily review (scheduled + workflow + outcome).**
Deployment fires at 08:00 → Program Chair lists new proposals (Event DB MCP) → workflow run with
CFP Reviewers → reviewers write scores (Event DB MCP) → chair writes `digest.md`, graded by an
outcome rubric → organizer reads the digest.

**Build the agenda (roster + advisor + approval).**
Organizer: "Accept the top 6 and build the agenda" → chair checks the fit with the Event DB
`check_agenda_fit` tool (everything already accepted, plus breaks and the end buffer) and
accepts only what fits → consults advisor on balance and running order → delegates slot
planning to the Scheduler → Scheduler proposes calendar events → each `create_event` pauses
for approval in the CLI → Speaker Liaison issues perk codes (vault env var; each call pauses
for approval too, and a declined code skips only that speaker).

**Write a speaker bio (runtime-created agent).** `concierge bio "<name>" "<facts>"` → the Bio
Writer, created once at runtime with `agents.create`, writes a short bio. This is a separate
command, not a step of the agenda run. *Possible later addition:* the chair could ask the Bio
Writer for each accepted speaker's bio at the end of the agenda run.

**Ask the helper.** `concierge ask "Where do I park?"` → Attendee Helper session with venues and
ops-notes stores attached read-only.

---

## 6. Phase 2: self-hosting

Phase 2 is source code plus a migration guide, not a live demo. The differences are the point:
the guide has an explicit "what you keep, what you lose" table.

### 6.1 Why self-host (the story)

The meetup grows into a conference series run by a company whose security team requires that
attendee data (names, emails, dietary needs) and tool execution stay in its network (2a), and
later that agent definitions and session history be stored in its own database with model calls
routed through its own gateway or cloud provider (2b).

### 6.2 Phase 2a: self-hosted sandboxes

Agent loop stays at Anthropic; tools run in a container you run. Code: `phase2/a-self-hosted-sandbox/`.

- `managed/environments/self-hosted.yaml` with `config: {type: self_hosted}`; same agents.
- `worker.py`: the Python SDK `EnvironmentWorker`, run in Docker, wired for graceful shutdown
  and OpenTelemetry (tool spans now come from your worker).
- CloudCredits: `environment_variable` vault credentials are not supported here, so the perk
  call becomes a **custom tool** executed by the host-side orchestrator, which holds the key.
- Memory stores still work through the SDK worker's sync (not the `ant` CLI worker).

### 6.3 Phase 2b: self-hosted Managed Agents (the service)

You run `cma-server` (API, agent loop, Postgres storage) and the workers. Access to the release
comes through the Anthropic account team, so most attendees will read this part rather than run
it. Code: `phase2/b-self-hosted-service/`.

- Point the SDK and `ant` at the server with `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` (the
  server API key).
- Recreate agents, memory stores, and vault containers with `ant apply` (nothing copies over).
- Agent files rewritten for the differences: `coordinator` multiagent type, no advisor, no
  workflows; Event DB and Calendar use `static_bearer`.
- Daily review becomes a cron entry that calls `concierge review run --direct`.
- MCP hosts listed under `mcp.allowed_hostnames` in the server settings.

### 6.4 What you keep, what you lose

| Feature | Phase 1 (hosted) | 2a (self-hosted sandbox) | 2b (self-hosted service) |
|---|---|---|---|
| Agents via `ant apply` | ✅ | ✅ | ✅ (recreate on your server) |
| On-the-fly overrides | ✅ | ✅ | ✅ |
| Memory stores | ✅ live mount | ✅ SDK worker syncs on an interval | ✅ worker syncs |
| Vault `mcp_oauth` | ✅ auto-refresh | ✅ | ❌ use `static_bearer`, rotate yourself |
| Vault `environment_variable` | ✅ | ❌ use a host-side custom tool | ⚠️ only with the egress gateway enabled |
| Scheduled deployments | ✅ | ✅ | ❌ use cron |
| Advisor | ✅ | ✅ | ❌ |
| Dynamic workflows | ✅ | ✅ | ❌ coordinator with listed subagents only |
| MCP servers | ✅ | ✅ | ⚠️ hosts must be in `mcp.allowed_hostnames` |
| Files API / file resources | ✅ | ❌ resources other than memory stores rejected | ❌ use base64 or the worker's directory |
| Webhooks | ✅ | ✅ | ❌ |
| Tool-call traces | API tracing | Your worker emits tool spans | Your server and worker |
| Choice of inference provider | Claude API | Claude API | Claude API, Bedrock, Google Cloud, Foundry, or your gateway |
| Where history lives | Anthropic | Anthropic | Your Postgres |

The self-hosted differences page doesn't say how OpenTelemetry, outcomes, permission policies, or
session budgets behave on a self-hosted server; the phase 2b guide marks them "verify in the
operator guide shipped with the release".

---

## 7. Repository layout

```
conference-concierge/
├── pyproject.toml            # hatchling, Ruff, pytest settings
├── README.md                 # quickstart and demo script
├── docker-compose.yml        # Jaeger (accepts OTLP directly)
├── docs/
│   ├── SPEC.md
│   └── guides/               # task guides (§8)
├── managed/                  # everything `ant apply` manages; claude-lock.json lives here
│   ├── agents/<agent>/agent.md
│   ├── environments/cloud.yaml
│   ├── memory_stores/*.yaml
│   ├── vaults/concierge.yaml
│   └── deployments/daily-review.yaml
├── content/                  # venues, rubrics, personas, sample proposals, seed notes
├── src/concierge/
│   ├── cli.py                # `concierge` Typer app
│   ├── config.py, managed.py # settings; IDs from claude-lock.json
│   ├── catalog.py, proposals.py, perks.py, clients.py, state.py
│   ├── telemetry.py          # OpenTelemetry setup
│   ├── sessions.py           # event loop: streaming, approvals, custom tools
│   ├── moderation.py, abstracts.py, bios.py, review.py, attendee.py
│   ├── memory.py, vaults.py, oauth_client.py
│   ├── portal/               # Starlette proposal form and board, served by `concierge serve`
│   └── services/             # OAuth server, Calendar MCP, Event DB MCP, CloudCredits API
├── phase2/
│   ├── a-self-hosted-sandbox/
│   └── b-self-hosted-service/
└── tests/
```

Python standards: Python 3.12+, `uv` (or `pip` + `venv`) for virtual environments, `pyproject.toml`
as the single config, Ruff for linting and formatting, type hints throughout, Pydantic models at
boundaries, pytest for tests. Secrets come from environment variables or a `.env` file that is
git-ignored; nothing secret is committed.

---

## 8. Task guides

Each guide is short (goal, prerequisites, numbered steps, "try it", "what to notice"). Each step
names the file and the `Step N` marker to search for. In code, markers look like:

```python
# Guide 05 · Wiring up OpenTelemetry · Step 2: register the tracer provider before the first call
```

| # | Guide | Feature | Main source |
|---|---|---|---|
| 00 | Setting up the project | uv, venv, Ruff, `.env`, tunnel | `pyproject.toml`, `README.md` |
| 01 | Declaring an agent and applying it with the CLI | `ant apply`, lock file | `managed/agents/`, `managed/environments/` |
| 02 | Versioning an agent and pinning sessions | versioning | `managed/agents/attendee-helper/agent.md`, `attendee.py` |
| 03 | Creating an agent on the fly | `agent_with_overrides`, runtime create | `abstracts.py`, `bios.py` |
| 04 | Giving agents system-level memory | memory stores | `managed/memory_stores/`, `memory.py`, `attendee.py` |
| 05 | Wiring up OpenTelemetry | SDK + API tracing | `telemetry.py`, `docker-compose.yml` |
| 06 | Storing secrets in a vault | `environment_variable`, `static_bearer` | `vaults.py`, Speaker Liaison |
| 07 | Passing OAuth credentials from the client to an MCP server | `mcp_oauth`, OAuth server | `oauth_client.py`, `services/oauth.py`, `services/calendar_mcp.py` |
| 08 | Configuring your orchestrator for multi-agent | roster, workflows | `managed/agents/program-chair/agent.md`, `review.py` |
| 09 | Adding an advisor | advisor | Program Chair |
| 10 | Scheduling an agent | deployments | `managed/deployments/daily-review.yaml`, `review.py` |
| 11 | Grading work with outcomes | outcomes | `abstracts.py`, `managed/deployments/daily-review.yaml`, `sessions.py` |
| 12 | Approvals and budgets | permission policies, session budgets | `sessions.py`, Scheduler agent |
| 13 | Moderating user input | Messages API structured output | `moderation.py` |
| 20 | Moving tools into your own sandbox | self-hosted sandbox | `phase2/a-self-hosted-sandbox/` |
| 21 | Migrating to self-hosted Managed Agents | self-hosted service | `phase2/b-self-hosted-service/` |

---

## 9. Demo script (about 20 minutes)

1. The setup: show `managed/`, run `ant apply --dry-run`, then apply. (Guide 01)
2. Audience submits talks from phones; each typed title gets moderated. (03, 11, 13)
3. Fire the daily review manually; watch the workflow run fan out in the Console. (08, 10)
4. Accept talks; build the agenda; advisor consult; approve calendar bookings live. (09, 12, 07)
5. Speaker Liaison issues a perk; show the placeholder for `$CLOUDCREDITS_API_KEY`. (06)
6. Ask the helper about parking at the new venue; show memory. (04)
7. Open Jaeger and follow one trace end to end. (05)
8. Slide: phase 2 keep/lose table. (20, 21)

---

## 10. Decisions (organizer, 2026-11-19)

1. One member profile with attendee and speaker roles.
2. The additional features (§5.1) are in, each with a task guide: agent versioning (Guide 02),
   outcomes (Guide 11), permission policies and session budgets (Guide 12).
3. Phase 2 is split into 2a (self-hosted sandbox) and 2b (self-hosted service).
4. The repository is the `conference-concierge` GitHub repo.
5. The sample event is called "AI Meetup".

## 11. Sources

- Managed Agents docs (Claude API reference bundled with Claude Code, checked 2026-11-18).
- https://platform.claude.com/docs/en/managed-agents/self-hosted
- https://platform.claude.com/docs/en/managed-agents/self-hosted/differences
- https://platform.claude.com/docs/en/managed-agents/self-hosted/call-the-api
- https://platform.claude.com/docs/en/managed-agents/self-hosted/quickstart
