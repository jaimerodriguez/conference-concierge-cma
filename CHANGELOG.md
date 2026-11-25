# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### 2026-11-24

#### Changed
- The GitHub repository is now `jaimerodriguez/conference-concierge-cma`. The README's issue
  and pull request links, the repository name in `docs/SPEC.md` (layout and decisions), and
  the example path in `phase2/b-self-hosted-service/cron/daily-review.cron` use the new name.
  `pyproject.toml` lists the repository and issues URLs. The Python package keeps its name,
  `conference-concierge`.
- README: a "Get the code" step (`git clone` and `cd conference-concierge-cma`) before setup,
  and a link to the companion write-up on jaimerodriguez.com.
- Docs scrub before going public: `docs/SPEC.md` no longer says the Speaker Liaison drafts
  welcome notes (it issues and records perk codes); Guide 21 says to copy
  `env.selfhosted.example` to `.env.selfhosted`; Guide 11 drops a repeated bullet; small
  wording and whitespace fixes in the README and Guide 04.
- `tests/test_publish.py` uses a made-up vault ID instead of a real one.

### 2026-11-23

#### Added
- `phase2/a-self-hosted-sandbox/.env.example` lists the worker's two variables,
  `ANTHROPIC_ENVIRONMENT_ID` and `ANTHROPIC_ENVIRONMENT_KEY`. Copy it to `.env` in that
  folder (git-ignored) as an alternative to shell exports. Guide 20 "Try it" and the
  top-level `.env.example` now say that the worker does not read the top-level `.env`.

#### Changed
- `concierge setup vault` with `CONCIERGE_ENVIRONMENT=self-hosted` now deletes the
  CloudCredits `environment_variable` credential instead of only skipping it. Sessions in
  a self-hosted environment are refused while their vault holds one, so `issue_perks.py`
  failed with a 400. Running `setup vault` in cloud mode puts the key back from `.env`.
  Guide 20 "Try it" now runs `setup vault` first.
- The phase 2a worker logs at INFO (`LOG_LEVEL` overrides it), so `docker compose up`
  shows each claimed session instead of printing nothing. It wraps the SDK's built-in
  tools to log what each call ran on (`tool ran in this container: read /mnt/memory/...`)
  in place of the SDK's bare `executing tool tool=read tool_use_id=...` line.
  The SDK's "tool 'issue_perk_code' not owned by this runner" line, which reads like a
  warning, now says "custom tool issue_perk_code runs in your client, not here".
- With `CONCIERGE_ENVIRONMENT=self-hosted`, every agent command ends by saying that
  built-in tools ran in your worker container. `issue_perks.py` now prints progress like
  the other commands (`[Speaker Liaison] reading the accepted proposals`), marks each
  `issue_perk_code` call as run by the script, not the worker, and renders the agent's
  reply as Markdown. Guide 20 has a "What to look for" section with sample
  output from both terminals.
- Guide 21 says why phase 2b is not a live demo: self-hosted Managed Agents is gated, and
  access comes through your Anthropic account team.

#### Fixed
- The phase 2a sandbox worker exited at start with `can't open file
  '/opt/concierge/worker.py': [Errno 13] Permission denied` when the checkout's files were
  private (mode 0600). The Dockerfile now copies `worker.py` with `--chmod=0644` and
  creates `/opt/concierge` beforehand, so the non-root `sandbox` user can read it whatever
  the file mode in your checkout.
- `.env.selfhosted` (phase 2b, holds your server's API key) is now git-ignored, like `.env`.
- Docs pass before the repo goes public:
  - Guide 05 said to restart `concierge services`; the command is `concierge serve`. Its
    "Try it" comment said the command proposes a session; it proposes a talk.
  - `docs/SPEC.md`: code markers are `Guide NN · <title> · Step N`, not `Step N of <guide>`;
    the Abstract Writer's outcome is graded against `content/rubrics/abstract.md`, not the
    track rubrics; the portal is Starlette, not FastAPI; session budgets list the real caps
    ($0.50 abstract, $0.25 Attendee Helper, $5 agenda and daily review); the Program Chair
    also records the organizer's acceptances in the Event DB; the Console viewer row no longer
    points to an `ant beta:sessions connect` tip that no guide has.
  - Small punctuation and trailing-space fixes in Guides 04, 05 and 11.
  - `docs/SPEC.md` section 9: the demo script is about 15 minutes, matching the README.

#### Removed
- `docs/TROUBLESHOOTING.md` is no longer tracked (kept locally and git-ignored), and the
  README no longer links to it. `concierge doctor` stays the first stop.

### 2026-11-21

#### Added
- `concierge setup public` puts the sample values back in the resource files so they are
  safe to commit to a public repo: your tunnel host becomes `concierge.example.com` again
  and the deployment's `vault_ids` becomes `[]`, in `managed/` and
  `phase2/b-self-hosted-service/`. `--check` only lists the files that still hold your
  values and exits 1 if any do. `setup host` and `setup deployment` restore your values
  afterwards. The logic lives in `src/concierge/publish.py`; README "Publishing your copy"
  has the steps.

- `concierge propose --abstract TEXT` and `--abstract-file PATH` (`-` reads stdin) submit
  your own abstract, like unchecking "Let AI generate abstract for me" in the portal. With
  neither, the Abstract Writer writes it, as before. Title and abstract are moderated
  together and no agent session runs.

- `concierge data sample` adds a fixed set of ten proposals from the new
  `content/sample_proposals.yaml`: five solid, AI-centered proposals with 60-120 word
  abstracts, then five problem cases the review should catch (a title that does not match
  its abstract, inappropriate content, a prompt injection, a sales pitch, a workshop in a
  lightning slot). The output's Case column says which is which; it is never saved, so
  reviewers judge the text alone. Offline, every proposal is saved as written, so the
  inappropriate one reaches the reviewers ("Respectful" declines it). With `--generate`, the
  accurate ones get Abstract Writer abstracts and the problem cases go through moderation,
  which stops the inappropriate one and the injection.

- Event DB `check_agenda_fit` tool (`src/concierge/agenda.py`): counts every accepted
  proposal against the evening's talk time after breaks (one per full hour after the first)
  and the end buffer, and says which extra proposals fit, taken in the order given. The
  arithmetic is code, not prompt, so the chair and the Scheduler read the same numbers.
  `content/event.yaml` gains `slots.buffer_minutes` (default 10). Live output shows it as
  "checking whether 4 more proposals fit in the evening".

- `review run` shows the delegation inside a workflow run: the run's plan and phase, a line
  as each CFP Reviewer starts (numbered, with how many run at once) and a line as each
  finishes, with the score and recommendation it saved. The chair's reads after the run are
  labelled as reading the reviews the reviewers saved. A run thread's tool calls are not on
  the session stream, so `follow_session` lists each run thread's own events when it ends
  and passes them on as a `ThreadFinished` report. `--verbose` adds each reviewer's tool
  calls.
- Guide 08: Step 6 (seeing inside a workflow run), sample output with how to read it, and
  what to look for in the Console session viewer (thread lanes, Threads tab, a reviewer's
  transcript). `docs/CLI.md` regenerated.

- `agenda build` shows the advisor consultation in two lines: "[Program Chair] consulting
  its advisor ..." when the platform starts the advisor's thread, and "[Advisor] advised the
  Program Chair (Opus 5.5, 20 s, $0.10) ..." when it ends, with the model, duration and cost
  read from the advisor thread's record (`sessions.threads.retrieve`), since the advice
  itself arrives redacted. `--verbose` adds the tokens the advisor read and wrote. The new
  `AdviceGiven` report is made in `follow_session` (marker `Guide 09 · Step 3`).
- Guide 09: Step 3 (seeing the consultation), how a consultation works, sample output with
  how to read it, what to look for in the Console, and a note that the prompt's "when"
  decides whether the advice can still change the bookings. `docs/CLI.md` regenerated.

#### Fixed
- With `OTEL_EXPORTER_OTLP_ENDPOINT` set but nothing listening there (Jaeger not started),
  every command ended with three `Transient error ... Connection refused` lines, a
  `Failed to export spans batch` line, and about six seconds of waiting. Tracing now checks
  the endpoint once at start; if nothing answers, it prints one line saying tracing is off
  for this run (start Jaeger or unset the variable, Guide 05) and the command runs without
  it. `concierge doctor` adds a tracing line: off, collector answers, or nothing answers.
  It never fails the check, since tracing is optional. `OTEL_SDK_DISABLED=true` also turns
  tracing off.
- `concierge serve` traced as `concierge-cli` instead of `concierge-portal`: the CLI's
  start-up hook registered the provider first. Guide 05 also named the command
  `concierge services`; it is `concierge serve`.
- `--verbose` raw tool names such as `[eventdb.list_proposals]` were swallowed by Rich as
  markup and never printed; progress lines are now escaped.
- `agenda build`: a reply to the Program Chair now shows the chair's answer. Before, the CLI
  read the session history after sending the reply, took the idle event that ended the
  previous turn as the end of the new one, and returned at once, so each reply was sent and
  answered but the answer was never shown and the prompt repeated.

#### Changed
- The Attendee Helper (`concierge ask`) ends each answer with a statement, never a question
  or an offer of more help: the attendee gets one answer and cannot reply. Edited in
  `managed/agents/attendee-helper/agent.md` and regenerated into the phase 2 copy; takes
  effect after `ant apply` from `managed/`.
- A moderation rejection no longer ends in a question. `concierge propose` and the portal
  used to print "How about: <suggestion>?", which invited a reply nobody could send (both
  answer once) and could end in ".?". They now say "You could resubmit with a title like:
  <suggestion>." (`suggestion_sentence` in `src/concierge/moderation.py`, which drops the
  model's ending punctuation). Both moderation prompts now ask for the alternative as a
  plain title and for the reason as a statement, never a question.
- The portal and `concierge propose` share one set of free checks before any model call
  (`check_submission` in `src/concierge/proposals.py`): email, title length, abstract length
  (50 to 1500 characters), track and persona. The CLI used to skip them, so an unknown
  persona or track crashed with a stack trace; it now prints the portal's message (which
  lists the valid ids) and exits 1. `propose` also exits 1 when moderation rejects the
  proposal. `--persona` help notes it only shapes AI-written abstracts.

- Program Chair: consults its advisor before it asks the Scheduler to book, on the proposed
  acceptances and running order, instead of after the bookings, so the advice can change the
  plan. Guide 09 (intro, how a consultation works, sample output from a live run, what to
  notice), SPEC and the phase 2b rewrite in `make_managed.py` match.
- Program Chair: before accepting, calls `check_agenda_fit` with the proposals it means to
  accept; accepts only those that fit and names the rest for the organizer. An earlier run
  accepted four on top of eight already accepted: 160 minutes of talks in a 150-minute
  window, ending 21:20. The Scheduler checks again before booking and books nothing if the
  accepted proposals already overrun, unless the organizer has accepted the overrun.
- Speaker Liaison: a declined perk code skips only that speaker; it carries on with the rest
  and lists who was skipped and why. The chair treats a declined booking or code the same
  way. Approval for each code is unchanged.
- `agenda build`: declining without a reason now tells the agent that only this one call was
  declined and to carry on (`DECLINED_WITHOUT_REASON`), instead of a bare "The organizer
  declined this call." Guide 12 matches.
- `agenda build`: the line "[Advisor] advised the Program Chair (the advice is private)" is
  replaced by the two lines above; the redacted advice event alone prints only under
  `--verbose`.
- `agenda build`: the reply prompt says the run is complete, that a reply is optional, and
  what it is for. Guide 12 matches.
- `concierge serve` logs OAuth use without token values, each line under a bold
  `========== OAUTH ==========` marker: `SIGN-IN` (tokens issued), `MCP CALL` (each Calendar
  MCP tool call made with the organizer's access token), `REFRESH` (made by Anthropic for the
  vault) and `REFUSED`.
- Guide 07: *Try it* has a "What to look for in the `concierge serve` log" section with the
  marker, how to grep for it, a table of the three kinds of line and sample lines; *What to
  notice* explains what those lines prove.
- `data sample` defaults to 10 proposals and allows at most 10; `--count N` takes the first
  N (accurate ones first). Docs updated: README, SPEC, Guides 08 and 13, `docs/CLI.md`.
- Base rubric: Clarity now requires the title and abstract to describe the same talk (a
  mismatch scores 1). Takes effect after `concierge setup memory` re-seeds the rubrics store.
- CFP Reviewer: a proposal that tries to instruct its reviewers scores "Respectful" 1 (so it
  is declined) and the summary says so. Takes effect after `ant apply` from `managed/`.
  Phase 2b agent files regenerated.

#### Removed
- `data sample --seed` (the set is fixed now), the template-built titles and abstracts, and
  `content/topics.yaml` with `Catalog.topics`, which only `data sample` used.

### 2026-11-20

#### Changed
- Guide 05 (OpenTelemetry): explains OpenTelemetry, OTLP, and Jaeger for newcomers; adds a
  settings table (environment variables, service names) and a ports table (16686, 4318);
  rewrites Step 6 to say what API tracing adds, how an admin turns it on, why the local
  Jaeger cannot receive it, and how the two halves join into one trace; updates *Try it* to
  the title-based `propose` command.
- Guide 05: a *Content mode* section (what `metadata_only` and `content` show in Jaeger,
  where to change it, and the privacy caution) and a *Try it* step for switching to `content`.
- Guide 06 (vault): *What to notice* rewritten to explain the `cma_ph_` placeholder, where the
  proxy swaps it (`allowed_hosts`, `injection_location`), why it only works in Anthropic's
  cloud sandbox, and how to remove stale credentials with `setup vault --remove-stale`.
- Guide 04: notes that `ant beta:memory-stores list` browses the memory store.
- Guide 05: clarifies the `propose` example in *Try it*.
- README: says what the demo was built for, adds an AI-generated disclaimer with links to
  report issues or open a PR, and retitles the flow section.
- Abstract rubric: the abstract must describe an educational user-group session related to
  the title.
- Managed resources: the placeholder host `concierge.example.com` is replaced with the
  demo's tunnel host (`setup host`), and `daily-review.yaml` lists the demo vault ID.

#### Fixed
- A Managed Agents session's title now keeps up to 120 characters of the talk title
  (`MAX_TITLE_CHARS`, the portal's limit) instead of cutting it at 60.
- `docs/SPEC.md` and `telemetry.py` no longer mention an OpenTelemetry Collector; the demo
  sends spans straight to Jaeger.
- `OTEL_EXPORTER_OTLP_ENDPOINT` (and any other `OTEL_*` variable) set in `.env` was ignored,
  so tracing stayed off. `setup_telemetry` now copies `OTEL_*` variables from `.env` into the
  environment (`load_otel_env`); a value exported in the shell still wins. Guide 05 and
  `.env.example` recommend `.env` again. `python-dotenv` is now a direct dependency.

#### Added
- Docs: flow visuals in `docs/images/`: who does the work (README), the guide map (README and
  guides index), and an all-in-one journey for presentations. Editable HTML source and a
  render script are in `docs/images/source/`.
- Portal: a "Let AI generate abstract for me" checkbox, checked by default. Unchecked, the
  person writes their own abstract (50 to 1,500 characters, with a live counter). Title and
  abstract are moderated together with the same house rule before they are saved
  (`moderate_abstract`), no agent session runs, and the proposal's source is
  `manual_abstract`.
- Portal: email format checks in the browser and on the server (`normalize_email`).
- Portal: after an error the form keeps what was typed; the submit button disables itself
  while a proposal is sent; the status page links to the new proposal on the board.
- Portal: a submission that moderation rejects (or that fails) returns to the form with
  everything still filled in (email, title, abstract, checkbox, track, persona), the reason
  and any suggested alternative shown on top.
- Proposal board: groups "Accepted", "Reviewed" (reviewed and waitlisted), "Not this time"
  (declined), and "Awaiting review" (submitted, not reviewed yet). Each card shows title,
  an expandable abstract, the score out of 5 as a bar, the reviewer's feedback, a next step
  for its status, and the contact email at the bottom. Also: counts per group, a track filter
  (`/board?track=ai-ml`), Expand all / Collapse all, highest scores first, a link anchor per
  proposal, and a dark-mode palette.
- Proposal board: contact emails are masked, keeping the first two letters and the last
  letter before the @ (`ad***e@example.com`; three letters or fewer keep only the first).
- `Store.list_board_proposals()` for the board, so the Event DB `list_proposals` tool stays
  short for agents.

#### Changed
- Members are identified by a contact email instead of a first name: the `members.name`
  column is now `members.contact_email`, and proposals return `contact_email` instead of
  `speaker_name`. A database from before this change is migrated when the store opens; old
  first names become placeholder `name@example.com` addresses.
- `concierge propose --name` is now `--email` (default `sam@example.com`). `concierge
  proposals` and `concierge data sample` show a "Contact email" column.
- Sample speakers use `@example.com` contact emails; sample titles keep acronyms like "AI".
- The proposal form asks, in order: contact email, talk title (always required), the AI
  checkbox or the abstract, track, and persona. The topic list and the "type your own topic"
  field are gone: the title is what the Abstract Writer writes about, and the stored title is
  always the person's. `submit_proposal` and `write_abstract` take `title` instead of `topic`,
  and `concierge propose` takes a title. Every title is moderated (there are no predefined
  topics to skip the check). AI-written proposals have source `ai_abstract`.
- The abstract rubric requires the title given in the task, unchanged, and the Abstract
  Writer's prompt and description say so.
- `content/topics.yaml` now only seeds `concierge data sample`, with AI-centered topics
  (agents, distillation, training and fine-tuning, agent skills, RAG, evaluation, MCP, and
  more). With `--generate`, sample titles come from the templates and are moderated too.
- Speaker Liaison (both variants) and Scheduler prompts report the speaker's contact email
  instead of a name, since members no longer have one. Phase 2b copies updated to match.
- Portal styling: a header with navigation, panels, and status colors; the submit button
  reads "Submit talk proposal".

### 2026-11-19

#### Added
- `concierge data clear` empties the local Event DB's demo tables (members, proposals,
  reviews, calendar events, perks). It also resets the ops-notes memory store, the only store
  agents write during runs, to `content/ops-notes`: run-written notes are deleted and seed
  files restored. The confirmation lists counts per table and each remote note by name, and
  says the deletion is permanent (`--yes` skips it). `--local-only` skips the memory reset.
  If the API is unreachable, the local part still runs and the CLI says the notes were not
  reset. It keeps the Calendar sign-in (oauth tables), `content/`, the rubrics and venues
  memory, and the rest of the workspace.
- `concierge data sample` adds submitted proposals for `review run` (`--count 8` by default).
  It runs offline and free from templates (`--seed` repeats a set), or with `--generate` the
  Abstract Writer writes each abstract through the `propose` path, after stating the cost.
  Each sample speaker has a distinct name.
- `concierge agenda build`: when the Program Chair ends its turn, the CLI asks for a reply
  and sends it to the same session. An empty reply finishes.
- `concierge agenda build --session sesn_...` continues an earlier agenda session. With no
  reply text it re-attaches: it asks about any booking still waiting for approval, sends the
  answer, and keeps following. When a run books nothing, the CLI shows this command.

#### Changed
- Daily review task (`managed/deployments/daily-review.yaml`): the task now lists every part
  of the digest in order (start state, summary, table, Top three, Respectful, Not covered only
  when needed). Before, only the rubric listed them, so the first draft was often sent back.
  The task also tells the Program Chair to wait for each reviewer's reply before reading
  reviews back from the Event DB, which stops it from pinging the reviewer early.
- `concierge agenda build`: the default instruction now says how to break ties for the last
  places (prefer variety of tracks and speakers) and not to stop and ask.
- Speaker Liaison: issuing a perk code now waits for the organizer's approval, like a
  calendar booking. Its `bash` tool is `always_ask` instead of `auto`, which had refused the
  call as high risk. It makes one request per code, never a loop. The question reads
  "Issue a CloudCredits perk code ($50) for <speaker> (<member id>)?", with the raw command
  only under `--verbose`. `a` covers the remaining perk codes, never other shell commands.
  The host-tool variants (phase 1 and phase 2) issue codes through a custom tool and are
  unchanged.
- Live output (`src/concierge/progress.py`, `cli.py`):
  - The grader's reason starts where the grader says what is wrong, skipping the list of
    what passed. A reviewer's reply shows as `[CFP Reviewer] reported back: ...`.
  - Each approval is one plain question ("Book 'Break' in Main Hall, 19:20-19:30?") instead
    of the tool name and raw JSON, which now show only under `--verbose`. Answering `a`
    approves this and every remaining booking in the run. The reason is asked only after
    a "no".
  - A call waiting for approval is no longer also printed as a progress line.
  - While it works, each Program Chair message is one line. Its last message is shown in
    full when its turn ends, followed by a clearer reply prompt.
  - An agenda run ends with a summary: calendar events, bookings requested in this run, perk
    codes issued, and the session's cost so far.
  - Agent names come from thread status events too, so a re-attached run names the
    Scheduler correctly. The advisor shows as "Advisor", and its redacted reply is explained.
- `review run` on an empty queue suggests `data sample` as well as `propose`.
- Docs: `docs/CLI.md` regenerated. README "Demo data" section and a clean-start note in "The
  demo, in order". Guides 04, 06, 08, 09, 10, 11, 12 and 13 describe the new commands and
  behaviour. Guide 00 lists `setup deployment` and the second `ant apply`. SPEC lists the
  perk-code approval. TROUBLESHOOTING gives the mock tokens' real lifetime (15 minutes).
- Guide 00: the example `ant` profile is named `concierge-demo`.
- SPEC: the agenda flow no longer says the Bio Writer creates bios. Bios come from
  `concierge bio`, now its own key flow, with bios in the agenda run noted as a possible
  later addition.
- README: the step-by-step setup block reminds you that `setup all` does all of it, and
  `doctor` has its own block after the setup steps.

#### Fixed
- Following a session no longer stops when the event stream closes early (for example after
  a long wait at an approval prompt). `follow_session` reopens the stream up to 5 times and
  catches up from the session history. It skips events already shown and calls already
  answered, and ignores idle events from earlier turns.
- If reconnecting fails, the CLI says it lost the connection, that the session may be
  waiting for an approval, and how to re-attach, instead of printing `Stopped: None`.
- `propose` (and the portal) reuse an existing member with the same name instead of
  creating a second member, so one speaker with two proposals is one member.
- The live output no longer crashes on `--verbose` "bringing in" lines or workflow-run lines
  (they passed a style the line printer did not accept).
