# Guide 00 · Setting up the project

**You'll end up with:** the project installed in a virtual environment, the mock services
running behind a public address, and every resource created in your Claude workspace.

## Before you start
- Python 3.12 or later and [uv](https://docs.astral.sh/uv/).
- The `ant` CLI, version 1.40.0 or later (`ant --version`), signed in with `ant auth login`
  or with `ANTHROPIC_API_KEY` exported.
- A tunnel tool that gives you a public HTTPS address for a local port, such as `cloudflared`
  or `ngrok`. A fixed hostname saves you from re-applying files when it changes.
- Optional: Docker, for Jaeger (Guide 05) and the phase 2a worker (Guide 20).

## Which workspace?

Everything this demo creates (agents, environments, memory stores, vaults, deployments,
sessions) lives in **one Claude workspace**, and the workspace is decided by your
**credentials**, not by a setting in this repo:

| Where the workspace comes from | Used by |
|---|---|
| `ANTHROPIC_API_KEY`, if exported: the key belongs to one workspace | `ant` and the Python code |
| Otherwise your `ant` profile (`ant auth login` binds a profile to one org and workspace) | `ant` and the Python code |

`CONCIERGE_WORKSPACE` in `.env` is only used to print Console links to sessions. It cannot
move resources, and it does not change which workspace `ant apply` writes to. The two must
agree, which is why both exist: the code can't read the workspace from your credentials,
so you tell it once for the links.

Before you run `ant apply`, check where you will write:

```sh
ant auth status                      # shows the active profile, workspace, and which credential won
ant profile list
```

To work in a different workspace, use a profile for it, or a key from it:

```sh
ant auth login --profile concierge-demo --workspace-id wrkspc_01...   # or pick it in the browser
ant profile activate concierge-demo          # make it the default, or:
export ANTHROPIC_PROFILE=concierge-demo      # for this terminal (Windows: $env:ANTHROPIC_PROFILE = "concierge-demo")
```

An exported `ANTHROPIC_API_KEY` overrides every profile, so unset it if you want the profile.
Each workspace has its own `claude-lock.json` IDs: if you switch workspaces after applying,
delete `managed/claude-lock.json` first, or `ant apply` will look for resources that do not
exist there.

## Steps

**Step 1. Install.** `uv sync` creates `.venv/` and installs the project with its
development tools. All settings live in `pyproject.toml`.

```sh
uv sync
uv run ruff check . && uv run ruff format --check .   # lint and format check
uv run pytest                                          # tests need no API key
```

**Step 2. Configure.** Copy `.env.example` to `.env` and replace each `change-me` with a
value of your own. These are pretend secrets for the mock services. `.env` is git-ignored.

**Step 3. Start the mock services and the tunnel.** In two terminals:

```sh
uv run concierge serve                 # OAuth, Calendar MCP, Event DB MCP, CloudCredits, portal
cloudflared tunnel --url http://localhost:8000    # or: ngrok http 8000
```

The tunnel prints a public address such as `https://random-words-here.trycloudflare.com`
(with `ngrok http 8000`, it is on the `Forwarding` line). The address is the **tunnel
address**; its host part, `random-words-here.trycloudflare.com`, is the **tunnel host**.
Put the full `https` address in `.env` as `CONCIERGE_PUBLIC_BASE_URL` (no trailing slash) and
restart `serve`. This is the only place you type it. Anthropic's MCP proxy and the cloud sandbox call that address, which is why it must
be public.

The free `cloudflared` address changes whenever the tunnel restarts. Repeat Steps 3 to 5 with
the new address (and `concierge auth calendar`, since credentials are matched to a server by
URL), or use a named tunnel or a reserved ngrok domain to keep one address.

**Step 4. Write the tunnel host into the resource files.** The agent and environment files
are static, so the host is written into them once. The command reads it from `.env`, so
there is nothing to retype (and no typo to make). It refuses a `.env` address that is still the
sample or not `https`.

```sh
uv run concierge setup host
```

You can still pass a host (`uv run concierge setup host my-host.example.com`), but it warns
when that differs from `.env`.

**Step 5. Create the resources.** Run `ant auth status` first and confirm the workspace
(see above). Follow Guide 01, then:

```sh
uv run concierge setup memory     # Guide 04
uv run concierge setup vault      # Guide 06
uv run concierge auth calendar    # Guide 07
uv run concierge setup deployment # Guide 10: give the daily-review deployment its vault
cd managed && ant apply && cd ..  # again, from inside managed/: now with the deployment
uv run concierge doctor           # checks what is still missing
```
`uv run concierge setup all` runs all of these in order (README, "Set up and run").

## What to notice
- The split: **`ant` owns the control plane** (files under `managed/`), and **Python owns
  the data plane** (sessions started with the recorded IDs).
- Sessions bill runtime on top of tokens and their history is kept until you delete it.
  Every session in this demo carries a budget (Guide 12).

## Check that every address agrees

The tunnel address ends up in several places: `.env`, the files under `managed/`, the agents
stored in your workspace, and the credentials in the vault (which are matched to an agent's MCP
server by exact URL). A difference in any one, such as `http` against `https` or a mistyped
host, breaks a run in ways that are hard to trace. `doctor` lists them side by side and says
which one differs and what to run:

```sh
uv run concierge doctor            # also asks the API what is stored (agents, vault)
uv run concierge doctor --offline  # files only
```

The vault part shows each credential's name, type, and the server URL or secret name it is
stored for. Secret values are write-only in the API, so they are never shown.
