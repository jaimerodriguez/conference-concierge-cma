"""The ``concierge`` command line: every demo flow, one command each."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from concierge import wiring
from concierge.config import PLACEHOLDER_HOST, REPO_ROOT, get_settings
from concierge.managed import ManagedResources, NotAppliedError, PlaceholderHostError
from concierge.progress import Progress, first_sentence
from concierge.publish import (
    find_private_values,
    private_hosts,
    resource_files,
    restore_placeholders,
)
from concierge.services.store import PROPOSAL_STATUSES
from concierge.sessions import Decision, SessionResult, console_url
from concierge.state import load_state, update_state
from concierge.telemetry import setup_telemetry, shutdown_telemetry

app = typer.Typer(no_args_is_help=True, help="Conference Concierge: a Claude Managed Agents demo.")
setup_app = typer.Typer(no_args_is_help=True, help="One-time setup steps.")
auth_app = typer.Typer(no_args_is_help=True, help="Sign-ins.")
review_app = typer.Typer(no_args_is_help=True, help="The daily proposal review.")
agenda_app = typer.Typer(no_args_is_help=True, help="Agenda building.")
data_app = typer.Typer(
    no_args_is_help=True,
    help="Demo data from runs: clear it (local Event DB and the ops-notes memory), or add "
    "sample proposals.",
)
app.add_typer(setup_app, name="setup")
app.add_typer(auth_app, name="auth")
app.add_typer(review_app, name="review")
app.add_typer(agenda_app, name="agenda")
app.add_typer(data_app, name="data")

console = Console()


@app.callback()
def main(ctx: typer.Context) -> None:
    # Guide 05 · Wiring up OpenTelemetry · Step 1: set tracing up once, at process start,
    # before the Claude client is created. `serve` sets up its own service name.
    if ctx.invoked_subcommand != "serve":
        setup_telemetry("concierge-cli")


def _client() -> Any:
    from concierge.clients import get_client

    return get_client()


def _finish(result: SessionResult) -> None:
    """Print how a session ended and flush traces."""
    console.print(f"\n[dim]Session:[/dim] {console_url(result.session_id)}")
    if result.outcome_result:
        console.print(f"[dim]Outcome:[/dim] {result.outcome_result}")
    for run_id, ending in result.workflow_runs.items():
        console.print(f"[dim]Workflow run {run_id}:[/dim] {ending}")
    _explain_issues(result)
    if result.stop_reason is None:
        # The event stream kept closing before the session stopped (reconnects ran out).
        # The session is still there and may be waiting on an answer.
        console.print(_STREAM_CLOSED.format(session_id=result.session_id))
    elif not result.ok:
        console.print(f"[yellow]Stopped: {result.stop_reason}[/yellow]")
        if result.stop_reason == "budget_reached":
            console.print("The session hit its budget and is paused. Raise the budget to resume.")
    shutdown_telemetry()


_STREAM_CLOSED = (
    "[yellow]Lost the connection before the session finished, and reconnecting did not "
    "work.[/yellow] The session is still there and may be waiting for an approval. For an "
    "agenda session, re-attach with:\n"
    "  uv run concierge agenda build --session {session_id}"
)


def _explain_issues(result: SessionResult) -> None:
    """Explain what the session reported, by error type, and say it did not stop the run."""
    if not result.issues:
        return
    explanations: list[tuple[str, list[str]]] = []
    seen: set[tuple[str, str | None]] = set()
    client = None
    for issue in result.issues:
        key = (issue.kind, issue.credential_id or issue.mcp_server_name)
        if key in seen:
            continue
        seen.add(key)
        try:
            client = client or _client()
            lines = wiring.explain_issue(client, get_settings(), result.session_id, issue)
        except Exception as error:
            lines = [wiring._short(error)]
        if lines:
            explanations.append((issue.message, lines))
    if not explanations:
        return
    how = "it did not stop the run" if result.ok else f"the run stopped ({result.stop_reason})"
    console.print(f"\n[bold yellow]The session reported a problem to fix ({how}):[/bold yellow]")
    for message, lines in explanations:
        console.print(f"  [dim]{message}[/dim]")
        for line in lines:
            console.print(f"    {line}")
    console.print("  Run `uv run concierge doctor` to check the whole chain.")


VERBOSE = Annotated[
    bool, typer.Option("--verbose", help="Also show the raw tool names in the live output.")
]


def _progress(lead: str, verbose: bool, max_rounds: int | None = None) -> Progress:
    return Progress(console, lead=lead, verbose=verbose, max_rounds=max_rounds)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class _AskPerson:
    """Guide 12 · Approvals and budgets · Step 5: put the decision in front of a person.

    One plain question per call ("Book 'Talk' in Main Hall, 18:30-18:55?"). The default is to
    decide each one, since the approval is the point. Answering ``a`` approves this call and
    every later call of the same tool in this run, so five bookings need not be five questions.
    """

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.approve_rest: set[str] = set()

    def __call__(self, event: Any) -> Decision:
        from concierge.progress import describe_approval, perk_call

        server = getattr(event, "mcp_server_name", None)
        tool_input = dict(event.input)
        key: str | None = f"{server}.{event.name}" if server else event.name
        if server is None and event.name == "bash":
            # "a" covers the rest of the perk codes, never arbitrary shell commands.
            key = "cloudcredits.issue_code" if perk_call("bash", tool_input) else None
        question = describe_approval(server, event.name, tool_input, _member_email)
        if key is not None and key in self.approve_rest:
            console.print(f"[green]Approved (you said yes to all):[/green] {question[:-1]}")
            return Decision(allow=True)
        console.print(f"\n[bold yellow]{question}[/bold yellow]")
        if self.verbose:
            console.print(f"[dim]{key}[/dim]")
            console.print_json(json.dumps(event.input, default=str))
        answer = (
            typer.prompt(
                "  y = yes, n = no, a = yes to this and all the rest",
                default="n",
                show_default=True,
            )
            .strip()
            .lower()
        )
        if answer in ("a", "all"):
            if key is not None:
                self.approve_rest.add(key)
            return Decision(allow=True)
        if answer in ("y", "yes"):
            return Decision(allow=True)
        reason = typer.prompt(
            "  Why not? The agent reads this (Enter to skip)", default="", show_default=False
        )
        return Decision(allow=False, message=reason or DECLINED_WITHOUT_REASON)


_ask_person = _AskPerson()

# Sent when the organizer declines without typing a reason. A bare "declined" once made the
# Speaker Liaison stop every remaining perk code, so say what the decline covers.
DECLINED_WITHOUT_REASON = (
    "The organizer declined this one call and gave no reason. Do not retry it. Carry on with "
    "the rest of your task, and report this call as declined."
)


def _member_email(member_id: str) -> str | None:
    """A speaker's contact email from the local Event DB, for approval questions."""
    from concierge.services.store import Store

    try:
        member = Store(get_settings().db_path).get_member(member_id)
    except Exception:
        return None
    return member["contact_email"] if member else None


# --- services -----------------------------------------------------------------------


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on (your tunnel points here).")] = 8000,
    portal: Annotated[bool, typer.Option(help="Also serve the proposal form at /.")] = True,
) -> None:
    """Run the mock services (OAuth, Calendar MCP, Event DB MCP, CloudCredits) and the portal."""
    import uvicorn

    from concierge.catalog import get_catalog
    from concierge.portal.app import build_routes
    from concierge.services.app import build_app
    from concierge.services.store import Store

    setup_telemetry("concierge-portal")
    settings = get_settings()
    extra = build_routes(settings, Store(settings.db_path), get_catalog()) if portal else []
    console.print(f"Public address (set CONCIERGE_PUBLIC_BASE_URL): {settings.base_url}")
    uvicorn.run(build_app(settings, extra_routes=extra), host=host, port=port)


# --- setup --------------------------------------------------------------------------


@setup_app.command("host")
def setup_host(
    hostname: Annotated[
        str | None,
        typer.Argument(help="Defaults to the host in CONCIERGE_PUBLIC_BASE_URL (.env)."),
    ] = None,
) -> None:
    """Write your public tunnel host into the files under managed/.

    With no argument it uses the host from CONCIERGE_PUBLIC_BASE_URL in .env, so there is
    nothing to retype. Agent and environment files are static, so the host of the mock
    services is written into them once. Run this before `ant apply` (run from inside
    managed/), and again if the host changes.
    """
    settings = get_settings()
    if hostname is None:
        if PLACEHOLDER_HOST in settings.base_url:
            console.print(
                "[red]CONCIERGE_PUBLIC_BASE_URL in .env is still the sample address.[/red] "
                "Set it to your tunnel address (https://<your-host>) and run this again."
            )
            raise typer.Exit(1)
        scheme = urlsplit(settings.base_url).scheme
        if scheme != "https":
            console.print(
                f"[red]CONCIERGE_PUBLIC_BASE_URL is {settings.base_url}, which is not https.[/red] "
                "The cloud only calls https. Fix it in .env and run this again."
            )
            raise typer.Exit(1)
        hostname = settings.public_host
        console.print(f"Using the host from .env: [bold]{hostname}[/bold]")
    else:
        hostname = re.sub(r"^https?://", "", hostname).strip("/")
        if hostname.lower() != settings.public_host.lower():
            console.print(
                f"[yellow]warn[/yellow]  {hostname} differs from the host in .env "
                f"({settings.public_host}). `concierge doctor` will flag it."
            )
    previous = load_state(settings.state_path).get("managed_host", PLACEHOLDER_HOST)
    changed = 0
    for path in resource_files(_resource_roots(settings)):
        text = path.read_text(encoding="utf-8")
        if previous in text:
            path.write_text(text.replace(previous, hostname), encoding="utf-8")
            changed += 1
            console.print(f"  updated {path.relative_to(REPO_ROOT)}")
    update_state(settings.state_path, managed_host=hostname)
    console.print(f"{changed} files now point at {hostname}.")
    console.print(
        "Next, for the phase 1 steps, run [bold]ant apply from inside the managed/ folder[/bold] "
        "(`cd managed && ant apply`). Not from the repo root: that would also apply the "
        "phase 2 files under phase2/. See Guide 01."
    )


def _resource_roots(settings: Any) -> list[Path]:
    # The phase 2b files are generated from managed/, so they carry the same host.
    return [settings.managed_dir, REPO_ROOT / "phase2" / "b-self-hosted-service"]


@setup_app.command("public")
def setup_public(
    check: Annotated[
        bool,
        typer.Option("--check", help="Only list the files that hold your values; change nothing."),
    ] = False,
) -> None:
    """Put the sample host and an empty vault list back, so the files are safe to publish.

    Undoes `setup host` and `setup deployment` in managed/ and phase2/b-self-hosted-service/:
    your tunnel host goes back to concierge.example.com and the deployment's vault_ids back
    to []. Commit, then run `setup host` and `setup deployment` to get your values back.
    Do not run `ant apply` in between. With --check it changes nothing and exits 1 if any
    of your values are still in the files.
    """
    settings = get_settings()
    roots = _resource_roots(settings)
    hosts = private_hosts(load_state(settings.state_path).get("managed_host"), settings.public_host)
    findings = find_private_values(roots, hosts)
    if not findings:
        console.print("[green]No private host or vault ID in the resource files.[/green]")
        return
    if check:
        table = Table("File", "Private value")
        for finding in findings:
            table.add_row(str(finding.path.relative_to(REPO_ROOT)), finding.value)
        console.print(table)
        console.print("Run `uv run concierge setup public` to put the placeholders back.")
        raise typer.Exit(1)
    for path in restore_placeholders(roots, hosts):
        console.print(f"  restored {path.relative_to(REPO_ROOT)}")
    # `setup host` replaces whatever host it last wrote, which is now the placeholder again.
    update_state(settings.state_path, managed_host=PLACEHOLDER_HOST)
    if left := find_private_values(roots, hosts):
        for finding in left:
            console.print(
                f"[red]still there[/red]  {finding.value} in "
                f"{finding.path.relative_to(REPO_ROOT)} (edit it by hand)"
            )
        raise typer.Exit(1)
    console.print(
        "[green]The files are ready to commit.[/green] Afterwards, get your own values back "
        "with `uv run concierge setup host` and `uv run concierge setup deployment`. "
        "Do not run `ant apply` until you have."
    )


_FIRST_APPLY = ["agents", "environments", "memory_stores", "vaults"]


@setup_app.command("all")
def setup_all(
    yes: Annotated[
        bool, typer.Option("--yes", help="Pass --yes to `ant apply` (do not ask before applying).")
    ] = False,
    browser: Annotated[
        bool, typer.Option(help="Open the Calendar sign-in page automatically.")
    ] = True,
    reauth_calendar: Annotated[
        bool, typer.Option(help="Sign in to the Calendar again even if the vault has a token.")
    ] = False,
) -> None:
    """Run the whole phase 1 setup in order; safe to re-run, stops at the first failure.

    Steps: host from .env, `ant apply` (agents, environment, stores, vault), memory seeding,
    vault secrets, Calendar sign-in, the deployment's vault ID, `ant apply` again, `doctor`.
    `concierge serve` and your tunnel must already be running (the sign-in uses them).
    """
    from concierge.vaults import has_credential_for

    settings = get_settings()
    managed = ManagedResources(settings.managed_dir)
    total = 8

    def step(number: int, title: str) -> None:
        console.print(f"\n[bold]Step {number}/{total}: {title}[/bold]")

    def stop(number: int, title: str, why: str) -> typer.Exit:
        console.print(f"\n[red]Stopped at step {number} ({title}).[/red] {why}")
        console.print(
            "Fix that, then run `uv run concierge setup all` again. "
            "Finished steps are safe to repeat."
        )
        return typer.Exit(1)

    def apply(number: int, title: str, folders: list[str]) -> None:
        console.print("`ant apply` runs from inside managed/. It shows its plan and asks first.")
        try:
            code = managed.apply(folders, yes=yes)
        except RuntimeError as error:
            raise stop(number, title, str(error)) from None
        if code != 0:
            raise stop(
                number, title, f"`ant apply` exited with code {code} (see its output above)."
            )

    step(1, "write the host from .env into managed/")
    try:
        setup_host(None)
    except typer.Exit:
        raise stop(1, "host", "See the message above.") from None

    step(2, "ant apply: agents, environment, memory stores, vault")
    apply(2, "ant apply", _FIRST_APPLY)

    for number, title, action in (
        (3, "seed the memory stores", setup_memory),
        (4, "store the vault secrets", lambda: setup_vault(remove_stale=False, yes=False)),
    ):
        step(number, title)
        try:
            action()
        except typer.Exit:
            raise stop(number, title, "See the message above.") from None
        except Exception as error:
            raise stop(number, title, wiring._short(error)) from None

    step(5, "sign in to the Calendar (opens a browser)")
    try:
        signed_in = not reauth_calendar and has_credential_for(_client(), settings.calendar_mcp_url)
        if signed_in:
            console.print(
                "The vault already has a Calendar credential. Skipping the sign-in "
                "(`--reauth-calendar` or `concierge auth calendar` to redo it)."
            )
        else:
            console.print(
                "A browser tab opens for the organizer sign-in (the page is served by "
                "`concierge serve` through your tunnel). Without a browser, use "
                "`setup all --no-browser` and open the printed link yourself."
            )
            auth_calendar(browser=browser)
    except Exception as error:
        raise stop(
            5, "Calendar sign-in", f"{wiring._short(error)} Is `concierge serve` running?"
        ) from None

    step(6, "give the deployment the vault ID")
    try:
        setup_deployment()
    except Exception as error:
        raise stop(6, "deployment vault", wiring._short(error)) from None

    step(7, "ant apply: everything, including the deployment")
    apply(7, "ant apply (second pass)", [])

    step(8, "doctor")
    doctor(offline=False)
    console.print("\n[green]Setup is complete.[/green] Try `uv run concierge review run`.")


@setup_app.command("show")
def setup_show() -> None:
    """Show the IDs `ant apply` recorded, including the vault ID the deployment file needs."""
    lock_path = get_settings().managed_dir / "claude-lock.json"
    if not lock_path.exists():
        console.print("No claude-lock.json yet. Run `ant apply` from managed/ (Guide 01).")
        raise typer.Exit(1)
    table = Table("File", "ID")
    for path, entry in json.loads(lock_path.read_text(encoding="utf-8"))["resources"].items():
        table.add_row(path, str(entry.get("id")))
    console.print(table)


@setup_app.command("deployment")
def setup_deployment() -> None:
    """Put the applied vault's ID into the daily-review deployment file (Guide 10, Step 2)."""
    managed = ManagedResources(get_settings().managed_dir)
    if managed.set_deployment_vault():
        console.print(f"Wrote vault {managed.vault_id()} into deployments/daily-review.yaml.")
        console.print("Now run `ant apply` from inside the managed/ folder.")
    else:
        console.print("The deployment file already attaches the vault. Nothing to change.")


@setup_app.command("memory")
def setup_memory() -> None:
    """Seed the memory stores from content/ (venues, rubrics, ops notes). Safe to re-run."""
    from concierge.memory import seed_all

    for report in seed_all(_client()):
        console.print(
            f"{report.store}: {report.created} created, {report.updated} updated, "
            f"{report.unchanged} unchanged"
        )
    shutdown_telemetry()


@setup_app.command("vault")
def setup_vault(
    remove_stale: Annotated[
        bool,
        typer.Option(
            "--remove-stale",
            help="Delete vault credentials stored for addresses this app no longer uses.",
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask before deleting.")] = False,
) -> None:
    """Store the Event DB token and the CloudCredits API key in the vault."""
    from concierge.vaults import find_stale_credentials, store_static_secrets

    client = _client()
    for line in store_static_secrets(client):
        console.print(line)
    stale = find_stale_credentials(client)
    for credential in stale:
        console.print(
            f"[yellow]leftover[/yellow]  '{credential.display_name}' is stored for "
            f"{credential.auth.mcp_server_url}, an address this app no longer uses. "
            "It is ignored and harmless."
        )
    if stale and not remove_stale:
        console.print("Delete leftovers with `uv run concierge setup vault --remove-stale`.")
    if stale and remove_stale:
        if not yes and not typer.confirm(
            f"Permanently delete {len(stale)} credential(s) listed above?", default=False
        ):
            console.print("Nothing deleted.")
        else:
            vault_id = ManagedResources(get_settings().managed_dir).vault_id()
            for credential in stale:
                client.beta.vaults.credentials.delete(credential.id, vault_id=vault_id)
                console.print(f"deleted '{credential.display_name}'")
    console.print("Next: `concierge auth calendar` to add the organizer's OAuth tokens.")
    shutdown_telemetry()


@auth_app.command("calendar")
def auth_calendar(
    browser: Annotated[bool, typer.Option(help="Open the sign-in page automatically.")] = True,
) -> None:
    """Sign in as the organizer and store the Calendar OAuth tokens in the vault."""
    from concierge.oauth_client import sign_in
    from concierge.vaults import store_calendar_oauth

    settings = get_settings()
    tokens = sign_in(settings, open_browser=browser)
    vault_id = ManagedResources(settings.managed_dir).vault_id()
    console.print(
        store_calendar_oauth(
            _client(),
            vault_id,
            settings,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        )
    )
    console.print("The tokens are in the vault. They were never written to disk here.")
    shutdown_telemetry()


# --- flows --------------------------------------------------------------------------


@app.command()
def propose(
    title: Annotated[str, typer.Argument(help="The talk's title. It is always yours.")],
    email: Annotated[str, typer.Option(help="Member's contact email.")] = "sam@example.com",
    abstract: Annotated[
        str | None,
        typer.Option(
            help="Your own abstract. Leave it out (and --abstract-file) to let AI write one.",
            show_default=False,
        ),
    ] = None,
    abstract_file: Annotated[
        Path | None,
        typer.Option(
            "--abstract-file",
            help="Read your own abstract from a file, or from stdin with '-'.",
            show_default=False,
            dir_okay=False,
            allow_dash=True,
        ),
    ] = None,
    track: Annotated[str, typer.Option(help="Track id from content/tracks.yaml.")] = "fun",
    persona: Annotated[
        str,
        typer.Option(
            help="Speaker persona id from content/personas.yaml: the voice AI writes in. "
            "With your own abstract it is only saved with the member."
        ),
    ] = "weekend-hacker",
) -> None:
    """Submit a proposal from the terminal, with the same choices as the portal form.

    By default the Abstract Writer agent writes the abstract for your title.

    Pass --abstract or --abstract-file to write your own. Everything you type is moderated first.
    """
    from concierge.catalog import get_catalog
    from concierge.moderation import suggestion_sentence
    from concierge.proposals import check_submission, submit_proposal
    from concierge.services.store import Store

    if abstract is not None and abstract_file is not None:
        console.print("[red]Use --abstract or --abstract-file, not both.[/red]")
        raise typer.Exit(2)
    if abstract_file is not None:
        if str(abstract_file) == "-":
            abstract = sys.stdin.read()
        elif abstract_file.is_file():
            abstract = abstract_file.read_text(encoding="utf-8")
        else:
            console.print(f"[red]No abstract file at {abstract_file}.[/red]")
            raise typer.Exit(2)
    # The portal's free checks, before any model call: same order, same messages.
    if problem := check_submission(
        get_catalog(),
        contact_email=email,
        title=title,
        track_id=track,
        persona_id=persona,
        abstract=abstract,
    ):
        console.print(f"[red]{problem}[/red]")
        raise typer.Exit(1)

    settings = get_settings()
    busy = "Writing the abstract..." if abstract is None else "Checking your abstract..."
    with console.status(busy):
        outcome = submit_proposal(
            _client(),
            Store(settings.db_path),
            contact_email=email,
            persona_id=persona,
            track_id=track,
            title=title,
            abstract=abstract,
        )
    if outcome.proposal:
        console.print(f"[bold]{outcome.proposal['title']}[/bold]  ({outcome.proposal['id']})")
        console.print(outcome.proposal["abstract"])
    console.print(outcome.message)
    if outcome.suggestion:
        console.print(suggestion_sentence(outcome.suggestion))
    if outcome.session_id:
        console.print(f"[dim]Session:[/dim] {console_url(outcome.session_id)}")
    shutdown_telemetry()
    if not outcome.accepted_for_review:
        raise typer.Exit(1)


# --- demo data ----------------------------------------------------------------------


@data_app.command("clear")
def data_clear(
    yes: Annotated[bool, typer.Option("--yes", help="Delete without asking.")] = False,
    local_only: Annotated[
        bool,
        typer.Option(
            "--local-only", help="Only clear the local Event DB; leave the ops-notes memory alone."
        ),
    ] = False,
) -> None:
    """Delete the demo data from runs so the demo starts clean. Permanent.

    Local: empties members, proposals, reviews, calendar events, and perks in the Event DB.

    Cloud: resets the ops-notes memory store to content/ops-notes (deletes run notes).

    Keeps the Calendar sign-in, content/, rubrics and venues memory, and the workspace.
    """
    from concierge.services.store import Store

    settings = get_settings()
    store = Store(settings.db_path)
    counts = store.demo_data_counts()
    plans, remote_error = ([], None) if local_only else _plan_memory_resets(settings)

    console.print(f"[bold]Local Event DB[/bold] ({settings.db_path})")
    if any(counts.values()):
        table = Table("Table", "Rows to delete")
        for name, count in counts.items():
            table.add_row(name, str(count))
        console.print(table)
    else:
        console.print("  Nothing to delete: the demo tables are already empty.")
    console.print("  [dim]Kept: the Calendar sign-in (oauth tables) and content/.[/dim]")

    console.print("\n[bold]Cloud memory[/bold] (your Anthropic workspace)")
    if local_only:
        console.print("  Skipped (--local-only).")
    elif remote_error:
        console.print(
            f"  [yellow]Could not read the ops-notes memory store:[/yellow] {remote_error}"
        )
        console.print("  Only the local data will be cleared; the notes will not be reset.")
    for plan in plans:
        if plan.empty:
            console.print(f"  {plan.store}: already matches its seed in content/{plan.store}.")
            continue
        console.print(
            f"  {plan.store}: [bold red]permanently deletes[/bold red] "
            f"{_plural(len(plan.delete), 'note')} written during runs:"
        )
        for path, _memory_id in plan.delete:
            console.print(f"    - {path}")
        if plan.restore:
            console.print(f"  and restores from content/{plan.store}: {', '.join(plan.restore)}")
    console.print(
        "  [dim]Kept: the rubrics and venues memory, agents, vaults and credentials, sessions, "
        "and the deployment.[/dim]"
    )

    remote_work = [plan for plan in plans if not plan.empty]
    if not any(counts.values()) and not remote_work:
        console.print("\nNothing to clear.")
        return
    if not yes and not typer.confirm(
        "\nDelete all of the above? This cannot be undone.", default=False
    ):
        console.print("Nothing deleted.")
        raise typer.Exit(1)

    deleted = store.clear_demo_data()
    console.print(f"Local: deleted {_plural(sum(deleted.values()), 'row')}.")
    for plan in remote_work:
        try:
            _apply_memory_reset(settings, plan)
        except Exception as error:
            console.print(
                f"[yellow]Cloud: {plan.store} was not reset:[/yellow] {wiring._short(error)}"
            )
            continue
        console.print(
            f"Cloud: {plan.store} reset (deleted {_plural(len(plan.delete), 'note')}, "
            f"restored {_plural(len(plan.restore), 'seed file')})."
        )
    console.print("The demo starts clean.")


def _plan_memory_resets(settings: Any) -> tuple[list[Any], str | None]:
    """Plan the reset of every memory store agents write during runs, or say why not."""
    from concierge.memory import RUN_WRITTEN_STORES, plan_reset

    try:
        client = _client()
        managed = ManagedResources(settings.managed_dir)
        return [
            plan_reset(client, managed.memory_store_id(name), settings.content_dir / name, name)
            for name in RUN_WRITTEN_STORES
        ], None
    except Exception as error:
        return [], wiring._short(error)


def _apply_memory_reset(settings: Any, plan: Any) -> None:
    from concierge.memory import apply_reset

    apply_reset(_client(), plan, settings.content_dir / plan.store)


@data_app.command("sample")
def data_sample(
    count: Annotated[
        int,
        typer.Option(
            min=1,
            max=10,
            help="How many proposals to create, from the top of content/sample_proposals.yaml "
            "(the five accurate ones come first). Ten at most.",
        ),
    ] = 10,
    generate: Annotated[
        bool,
        typer.Option(
            help="Have the Abstract Writer write the accurate proposals' abstracts (the "
            "`propose` path, about a cent each); the problem cases go through moderation."
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --generate: do not ask first.")] = False,
) -> None:
    """Add sample talk proposals, status "submitted", so `review run` has work.

    Five are solid proposals; the rest are problem cases the review should catch: a title
    that does not match its abstract, inappropriate content, a prompt injection, a sales
    pitch, and a workshop squeezed into a lightning slot. The Case column says which is which
    and is never saved, so reviewers judge each proposal on its own text.

    Offline and free by default: every proposal is saved as written, so the inappropriate one
    reaches the reviewers. With --generate, moderation screens the problem cases first.
    Nothing in your Anthropic workspace is created.
    """
    from concierge.catalog import get_catalog
    from concierge.sample_data import (
        GENERATE_CENTS_EACH,
        create_offline,
        get_samples,
        pick_samples,
    )
    from concierge.services.store import Store

    settings = get_settings()
    store = Store(settings.db_path)
    catalog = get_catalog()
    samples = pick_samples(get_samples(), count)
    if not generate:
        created = create_offline(store, catalog, samples)
        _show_samples(list(zip(samples, created, strict=True)), store)
        console.print(f"Added {_plural(len(created), 'proposal')} (offline, no cost).")
        return

    from concierge.proposals import submit_proposal

    written = sum(sample.accurate for sample in samples)
    screened = len(samples) - written
    console.print(
        f"The Abstract Writer will write {_plural(written, 'abstract')}: about "
        f"${written * GENERATE_CENTS_EACH / 100:.2f} in total, one session each. "
        f"{_plural(screened, 'problem case')} keep their own abstracts and only go through "
        "moderation (a fraction of a cent each)."
    )
    if not yes and not typer.confirm("Go ahead?", default=False):
        console.print("Nothing created.")
        raise typer.Exit(1)
    client = _client()
    created = []
    for number, sample in enumerate(samples, start=1):
        doing = "Writing abstract" if sample.accurate else "Screening proposal"
        with console.status(f"{doing} {number} of {count} ({sample.contact_email})..."):
            outcome = submit_proposal(
                client,
                store,
                contact_email=sample.contact_email,
                persona_id=sample.persona,
                track_id=sample.track,
                title=sample.title,
                abstract=None if sample.accurate else sample.abstract,
            )
        if outcome.proposal:
            created.append((sample, outcome.proposal))
        elif sample.accurate:
            console.print(f"[yellow]Skipped {sample.contact_email}:[/yellow] {outcome.message}")
        else:
            console.print(
                f"[green]Moderation stopped[/green] {sample.contact_email} ({sample.case}): "
                f"{outcome.message}"
            )
    _show_samples(created, store)
    console.print(f"Added {_plural(len(created), 'proposal')}.")
    shutdown_telemetry()


def _show_samples(created: list[tuple[Any, dict[str, Any]]], store: Any) -> None:
    table = Table("ID", "Title", "Track", "Contact email", "Case")
    for sample, proposal in created:
        member = store.get_member(proposal["member_id"]) or {}
        case = sample.case if sample.accurate else f"[yellow]{sample.case}[/yellow]"
        table.add_row(
            proposal["id"],
            proposal["title"],
            proposal["track"],
            member.get("contact_email", "?"),
            case,
        )
    console.print(table)
    console.print(
        "[dim]The Case column is for you: it is not saved, so reviewers never see it. "
        "What each case should trigger: content/sample_proposals.yaml.[/dim]"
    )


@app.command()
def proposals(
    status: Annotated[
        str | None,
        typer.Option(
            help=f"Only show proposals with this status ({', '.join(PROPOSAL_STATUSES)})."
        ),
    ] = None,
) -> None:
    """List proposals in the local Event DB."""
    from concierge.services.store import Store

    table = Table("ID", "Title", "Track", "Contact email", "Status", "Score", "Rec.")
    for row in Store(get_settings().db_path).list_proposals(status=status):
        table.add_row(
            row["id"],
            row["title"],
            row["track"],
            row["contact_email"],
            row["status"],
            "" if row["overall"] is None else str(row["overall"]),
            row["recommendation"] or "",
        )
    console.print(table)


@review_app.command("run")
def review_run(
    direct: Annotated[
        bool, typer.Option(help="Start an ordinary session instead of firing the deployment.")
    ] = False,
    force: Annotated[
        bool, typer.Option(help="Start the review even when no proposal is waiting.")
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Also show each reviewer's own tool calls and the raw tool names.",
        ),
    ] = False,
) -> None:
    """Run the daily proposal review now and follow it, reviewer by reviewer.

    In a workflow run, each CFP Reviewer gets a line when it starts (with how many run at
    once) and when it finishes (with the score and recommendation it saved).
    """
    from concierge.review import (
        DIGEST_FILE,
        review_budget_cents,
        review_max_rounds,
        run_review_directly,
        run_scheduled_review_now,
    )
    from concierge.services.store import Store
    from concierge.sessions import read_output_file

    settings = get_settings()
    submitted = Store(settings.db_path).list_proposals(status="submitted")
    waiting = len(submitted)
    console.print(f"Checking the Event DB: {_plural(waiting, 'proposal')} waiting for review.")
    if waiting == 0 and not force:
        console.print(
            "Nothing to review, so no session was started (a review costs money). Add "
            "proposals with `uv run concierge data sample` (free) or `propose`, or run again "
            "with --force."
        )
        return
    cents = review_budget_cents(settings, direct=direct)
    console.print(f"Starting the daily review (budget up to ${cents / 100:.2f}).")
    client = _client()
    progress = _progress("Program Chair", verbose, review_max_rounds(settings.managed_dir))
    if direct:
        result = run_review_directly(
            client, on_event=progress, submitted_ids=[row["id"] for row in submitted]
        )
    else:
        result = run_scheduled_review_now(client, on_event=progress)
    if result.outcome_result not in (None, "satisfied"):
        console.print(
            "\n[bold yellow]The grader did not approve this digest "
            f"({result.outcome_result}). Treat it as unverified.[/bold yellow]"
        )
    digest = read_output_file(client, result.session_id, DIGEST_FILE)
    # Without a Files API (phase 2), fall back to what the chair said in its last message.
    console.print(Markdown(digest.decode("utf-8") if digest else result.text))
    _finish(result)


@review_app.command("runs")
def review_runs(
    limit: Annotated[int, typer.Option(help="How many recent runs to show.")] = 10,
) -> None:
    """Show recent firings of the scheduled review, including failed ones."""

    client = _client()
    deployment_id = ManagedResources(get_settings().managed_dir).deployment_id()
    deployment = client.beta.deployments.retrieve(deployment_id)
    console.print(f"Status: {deployment.status}. Next runs: {deployment.schedule.upcoming_runs_at}")
    table = Table("Run", "Trigger", "Created", "Session", "Error")
    for index, run in enumerate(client.beta.deployment_runs.list(deployment_id=deployment_id)):
        if index >= limit:
            break
        table.add_row(
            run.id,
            run.trigger_context.type,
            str(run.created_at),
            run.session_id or "",
            run.error.type if run.error else "",
        )
    console.print(table)


@agenda_app.command("build")
def agenda_build(
    instruction: Annotated[
        str | None,
        typer.Argument(
            help="What to ask the Program Chair. Default: accept the top four, breaking ties "
            "for variety, then book. With --session: your reply, or leave it out to re-attach "
            "and answer what is waiting.",
            show_default=False,
        ),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option(
            help="Continue this agenda session (sesn_...): answer any booking still waiting "
            "for approval, then follow it."
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Also show the advisor's token counts and the raw tool names.",
        ),
    ] = False,
) -> None:
    """Ask the Program Chair to build the agenda. You approve each calendar booking.

    Reply in the terminal when the chair ends its turn; an empty reply finishes.
    """
    from concierge.review import build_agenda

    if instruction is None and not session:
        instruction = DEFAULT_AGENDA_INSTRUCTION
    settings = get_settings()
    console.print(
        (f"Continuing {session}" if session else "Asking the Program Chair")
        + f" (budget up to ${settings.agenda_budget_cents / 100:.2f}). You approve each "
        "calendar booking; answer a to approve the rest at once."
    )
    progress = _progress("Program Chair", verbose)
    bookings: list[str] = []
    last_message: list[str] = []

    def on_event(event: Any) -> None:
        if event.type == "agent.mcp_tool_use" and event.name == "create_event":
            bookings.append(event.name)
        progress(event)

    def on_text(text: str) -> None:
        # While it works, one line per message; its last message is shown in full at the end.
        last_message[:] = [text]
        if verbose:
            console.print(Markdown(text))
        else:
            console.print(f"[cyan]\\[Program Chair][/cyan] {first_sentence(text)}")

    approver = _AskPerson(verbose)
    while True:
        last_message.clear()
        result = build_agenda(
            _client(),
            instruction,
            approver=approver,
            on_text=on_text,
            on_event=on_event,
            session_id=session,
        )
        session = result.session_id
        if last_message and not verbose:
            console.rule("Program Chair")
            console.print(Markdown(last_message[0]))
        if not result.ok or not _interactive():
            break
        # The chair may end its turn on a question (a tie, a missing detail). Answer it here
        # and it carries on in the same session, with everything it already knows.
        console.print(
            "\n[bold]This run is complete.[/bold] Every booking you approved is already made. "
            "A reply is optional: type one to answer a question the chair asked or to ask for "
            "a change, and it carries on in the same session with everything it already "
            "knows. Press Enter to finish."
        )
        reply = typer.prompt("Your reply (optional)", default="", show_default=False).strip()
        if not reply:
            break
        instruction = reply
    _agenda_summary(result, len(bookings))
    _finish(result)


def _agenda_summary(result: SessionResult, booked_now: int) -> None:
    """What the run left behind: bookings, perk codes, and the session's cost so far."""
    from concierge.services.store import Store

    if result.ok and not booked_now:
        console.print(_nothing_booked(result.session_id))
    store = Store(get_settings().db_path)
    counts = store.demo_data_counts()
    line = (
        f"\n[bold]Calendar:[/bold] {_plural(counts['calendar_events'], 'event')} "
        f"({booked_now} requested in this run). "
        f"[bold]Perk codes:[/bold] {counts['perks']} issued."
    )
    try:
        cost = _client().beta.sessions.retrieve(result.session_id).usage.list_cost
        if cost is not None:
            line += f" [bold]Cost:[/bold] ${int(cost.amount) / 100:.2f} for this session so far."
    except Exception:
        pass  # the summary is a convenience; the session link below has the cost too
    console.print(line)


DEFAULT_AGENDA_INSTRUCTION = (
    "Accept the four highest-scoring reviewed proposals. If scores tie for the last places, "
    "choose the ones that give the most variety of tracks and speakers, say which you chose "
    "and why, and do not stop to ask. Then build and book the agenda."
)


def _interactive() -> bool:
    import sys

    return sys.stdin.isatty()


def _nothing_booked(session_id: str) -> str:
    return (
        "\n[bold yellow]Nothing was booked.[/bold yellow] To answer the Program Chair later, in "
        "the same session:\n"
        f'  uv run concierge agenda build --session {session_id} "your answer"'
    )


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Your question, in quotes.")],
    verbose: VERBOSE = False,
) -> None:
    """Ask the Attendee Helper a question about the event or venue."""
    from concierge.attendee import ask_helper

    result = ask_helper(
        _client(),
        question,
        on_text=lambda text: console.print(Markdown(text)),
        on_event=_progress("Attendee Helper", verbose),
    )
    _finish(result)


@app.command()
def bio(
    name: Annotated[str, typer.Argument(help="The speaker's name.")],
    facts: Annotated[str, typer.Argument(help="Facts to work into the bio, in quotes.")],
    verbose: VERBOSE = False,
) -> None:
    """Write a speaker bio with an agent created at runtime (Guide 03)."""
    from concierge.bios import write_bio

    result = write_bio(_client(), name=name, facts=facts, on_event=_progress("Bio Writer", verbose))
    console.print(result.text)
    _finish(result)


@app.command()
def doctor(
    offline: Annotated[
        bool, typer.Option(help="Skip the checks that ask the Claude API what is stored.")
    ] = False,
) -> None:
    """Check the local setup, that every server URL agrees, and say what to do next."""
    settings = get_settings()
    checks: list[tuple[str, bool, str]] = [
        (
            f".env present ({REPO_ROOT / '.env'})",
            (REPO_ROOT / ".env").exists(),
            "cp .env.example .env",
        ),
        (
            "public address set",
            PLACEHOLDER_HOST not in settings.base_url,
            "set CONCIERGE_PUBLIC_BASE_URL to your tunnel address",
        ),
        (
            "mock secrets changed",
            "change-me"
            not in {
                settings.organizer_password,
                settings.eventdb_token,
                settings.cloudcredits_api_key,
            },
            "replace the change-me values in .env",
        ),
        (
            "agent files use your host",
            not ManagedResources(settings.managed_dir).files_with_placeholder_host(),
            "run `uv run concierge setup host`, then `ant apply` from inside managed/",
        ),
        (
            "managed files applied",
            (settings.managed_dir / "claude-lock.json").exists(),
            "run `ant apply` from managed/ (Guide 01)",
        ),
    ]
    for label, ok, fix in checks:
        mark = "[green]ok[/green]" if ok else "[red]todo[/red]"
        console.print(f"{mark}  {label}" + ("" if ok else f"  ->  {fix}"))
    _print_tracing_status()

    # Where the server address lives, and whether every copy agrees.
    rows, findings = wiring.check_local(settings)
    if not offline and (settings.managed_dir / "claude-lock.json").exists():
        try:
            client = _client()
        except Exception as error:  # no credentials, for example
            findings.append(wiring.Finding(None, "cloud checks", wiring._short(error)))
        else:
            remote_rows, remote_findings = wiring.check_remote(client, settings)
            rows += remote_rows
            findings += remote_findings
    if not offline and (settings.managed_dir / "claude-lock.json").exists():
        plan = ManagedResources(settings.managed_dir).pending_changes()
        excerpt = "\n      ".join(plan.output.splitlines()[:12])
        if plan.state == "none":
            findings.append(wiring.Finding(True, "managed/ files match what was applied", "", ""))
        elif plan.state == "pending":
            findings.append(
                wiring.Finding(
                    False,
                    "`ant apply --dry-run` shows changes that are not applied yet",
                    excerpt,
                    "run `ant apply` from inside managed/",
                )
            )
        else:
            findings.append(
                wiring.Finding(
                    None, "could not compare managed/ with what was applied", excerpt, ""
                )
            )
    findings = wiring.merge_deployment_findings(findings)
    console.print("\n[bold]What points where[/bold]")
    table = Table("Place", "Holds", show_header=True, header_style="dim")
    for row in rows:
        table.add_row(row.place, row.value)
    console.print(table)
    for finding in findings:
        mark = {True: "[green]ok[/green]", False: "[red]todo[/red]", None: "[yellow]skip[/yellow]"}[
            finding.ok
        ]
        if finding.harmless:
            mark = "[cyan]note[/cyan]"
        console.print(f"{mark}  {finding.label}")
        if finding.detail and finding.ok is not True:
            console.print(f"      {finding.detail}")
        if finding.fix and (finding.ok is False or finding.harmless):
            console.print(f"      -> {finding.fix}")

    console.print(
        "[dim]Workspace: resources go to the one your `ant` profile or API key belongs to. "
        f"Check with `ant auth status`. CONCIERGE_WORKSPACE ({settings.workspace}) only "
        "builds Console links.[/dim]"
    )
    if not all(ok for _, ok, _ in checks) or wiring.problems(findings):
        raise typer.Exit(1)


def _print_tracing_status() -> None:
    """One doctor line on tracing. Tracing is optional, so it never fails the check."""
    from concierge.telemetry import GUIDE, collector_reachable, otel_endpoint

    endpoint = otel_endpoint()
    if endpoint is None:
        console.print(
            f"[cyan]note[/cyan]  tracing off (OTEL_EXPORTER_OTLP_ENDPOINT unset; see {GUIDE})"
        )
    elif collector_reachable(endpoint):
        console.print(f"[green]ok[/green]  tracing collector answers at {endpoint}")
    else:
        console.print(
            f"[cyan]note[/cyan]  nothing answers at {endpoint} (OTEL_EXPORTER_OTLP_ENDPOINT), "
            "so commands run without tracing  ->  `docker compose up -d` from the repository "
            "root, or unset the variable"
        )


def entry_point() -> None:
    """Entry point: print setup problems as a message, not a traceback."""
    try:
        app()
    except (NotAppliedError, PlaceholderHostError) as error:
        console.print(f"[red]{error}[/red]")
        raise SystemExit(1) from None


if __name__ == "__main__":
    entry_point()
