# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
