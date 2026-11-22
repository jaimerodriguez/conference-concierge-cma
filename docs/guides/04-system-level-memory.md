# Guide 04 · Giving agents system-level memory

**You'll learn:** how to give agents knowledge that belongs to the *system*, not to a user.
Memory stores are scoped to the workspace. This demo has three, and none is per member:

| Store | Holds | Agents' access |
|---|---|---|
| `venues` | One profile per venue | read-only |
| `rubrics` | `base.md` plus one file per track | read-only |
| `ops-notes` | What the team has learned | read-write for the Chair and Scheduler, read-only for the Attendee Helper |

## Steps

**Step 1. Declare the stores.** The `description` is written for the agent.
Find it: `managed/memory_stores/venues.yaml`, marker `Guide 04 · ... · Step 1`.

**Step 2. Seed them from files.** Venue profiles and rubrics are markdown under `content/`.
Find it: `src/concierge/memory.py`, marker `Step 2`.

**Step 3. Update safely.** A `content_sha256` precondition stops a re-seed from overwriting
something an agent wrote in the meantime.
Find it: `src/concierge/memory.py`, marker `Step 3`.

**Step 4. Attach stores to a session.** Each store is mounted at
`/mnt/memory/<store-name>/` and read with the ordinary file tools.
Find it: `src/concierge/attendee.py`, marker `Step 4`.

## Try it
```sh
uv run concierge setup memory
uv run concierge ask "Is there vegan food?"
```
Then edit `content/event.yaml` to use `riverside-library`, ask about parking again, and
compare. Add a venue by adding one markdown file and seeding again.

## What to notice
- Stores attach at session creation only, up to eight per session.
- **Access is a security decision.** The public can talk to the Attendee Helper, so its
  stores are read-only: nobody in the audience can plant a note for later sessions.
- Every change creates a memory version, so you can audit and roll back in the Console.
- Never put secrets in memory. It is replayed into every session that mounts the store.
- ops-notes is the one store agents write (`read_write` for the Program Chair), so practice
  runs leave notes there. `uv run concierge data clear` resets it to `content/ops-notes`: it
  lists the run-written notes by name, deletes them after you confirm, and restores the seed
  files. `--local-only` leaves it alone.
- You can navigate and list the memory store using the ant CLI: `ant beta:memory-stores list` . Use the arrows to expand and navigate the store details.  