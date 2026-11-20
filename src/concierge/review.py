"""The Program Chair's two jobs: the daily proposal review and building the agenda.

Both run the same coordinator agent (``managed/agents/program-chair/agent.md``), which
delegates to its roster, starts workflow runs for large batches, and consults its advisor.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from anthropic import Anthropic

from concierge.config import Settings, get_settings
from concierge.managed import ManagedResources
from concierge.perks import run_custom_tool
from concierge.sessions import (
    Approver,
    EventCallback,
    SessionResult,
    budget,
    deny_all,
    follow_session,
    user_message,
)

DEPLOYMENT_FILE = "deployments/daily-review.yaml"
DIGEST_FILE = "digest.md"


def _chair_resources(managed: ManagedResources) -> list[dict[str, Any]]:
    """Memory the chair's sessions mount. Subagent threads share the same container."""
    return [
        {
            "type": "memory_store",
            "memory_store_id": managed.memory_store_id("venues"),
            "access": "read_only",
            "instructions": "Venue profiles, including each venue's rooms and AV.",
        },
        {
            "type": "memory_store",
            "memory_store_id": managed.memory_store_id("rubrics"),
            "access": "read_only",
            "instructions": "Scoring rubrics: base.md plus tracks/<track-id>.md.",
        },
        {
            "type": "memory_store",
            "memory_store_id": managed.memory_store_id("ops-notes"),
            "access": "read_write",
            "instructions": "What the team has learned. Read before planning; add dated notes.",
        },
    ]


def load_review_kickoff(
    managed_dir: Path, submitted_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """Read the review's kickoff events from the deployment file, the single source of truth.

    Pass ``submitted_ids`` (what the CLI found just before starting) to state the run's start
    state in the task, so the grader and the agent agree on what was in scope. A scheduled
    firing cannot be told this, so there the agent records the start state itself (see the
    description in the deployment file).
    """
    events = _deployment(managed_dir)["initial_events"]
    if submitted_ids is not None:
        found = ", ".join(submitted_ids) if submitted_ids else "none"
        note = (
            f"\nThe start state was checked just before this run: {len(submitted_ids)} "
            f"submitted proposal(s): {found}. Use exactly this start state."
        )
        events = [dict(event) for event in events]
        events[0]["description"] = events[0]["description"].rstrip("\n") + note
    return events


def _deployment(managed_dir: Path) -> dict[str, Any]:
    return yaml.safe_load((managed_dir / DEPLOYMENT_FILE).read_text(encoding="utf-8"))


def review_max_rounds(managed_dir: Path) -> int | None:
    """How many grader rounds the review's outcome allows (for "round 1 of 3")."""
    events = _deployment(managed_dir).get("initial_events") or []
    rounds = events[0].get("max_iterations") if events else None
    return int(rounds) if rounds else None


def review_budget_cents(settings: Settings, *, direct: bool) -> int:
    """The spend cap of the run: the deployment's budget, or the settings' for --direct."""
    if direct:
        return settings.agenda_budget_cents
    amount = (_deployment(settings.managed_dir).get("budget") or {}).get("max_list_cost", {})
    return int(amount.get("amount", settings.agenda_budget_cents))


def run_scheduled_review_now(
    client: Anthropic, *, on_event: EventCallback | None = None, settings: Settings | None = None
) -> SessionResult:
    """Fire the scheduled deployment by hand and follow the session it creates.

    # Guide 10 · Scheduling an agent · Step 4: a manual run
    A manual run creates a session immediately with the deployment's exact configuration.
    It is how you test a schedule, and how the presenter triggers the review on stage.
    """
    settings = settings or get_settings()
    deployment_id = ManagedResources(settings.managed_dir).deployment_id()
    run = client.beta.deployments.run(deployment_id)
    if run.session_id is None:
        raise RuntimeError(f"The run {run.id} did not create a session: {run.error}")
    # Guide 10 · Step 5: a deployment run is just a session. Follow it like any other.
    # We are attached this time, but the scheduled firing has nobody watching, so we keep
    # the same answer the unattended run gets: deny anything that asks.
    return follow_session(
        client, run.session_id, approver=deny_all, on_event=on_event, include_history=True
    )


def run_review_directly(
    client: Anthropic,
    *,
    on_event: EventCallback | None = None,
    settings: Settings | None = None,
    submitted_ids: list[str] | None = None,
) -> SessionResult:
    """Run the same review as an ordinary session, without the deployment.

    This is what a cron job calls where scheduled deployments do not exist (phase 2b,
    Guide 21). Everything else about the review stays the same.
    """
    settings = settings or get_settings()
    managed = ManagedResources(settings.managed_dir)
    session = client.beta.sessions.create(
        agent=managed.agent_id("program-chair"),
        environment_id=managed.environment_id(),
        title="Daily proposal review",
        vault_ids=[managed.vault_id()],
        resources=_chair_resources(managed),
        # With workflows on, always give the session a budget: every agent in a run uses tokens.
        budget=budget(settings.agenda_budget_cents),
        initial_events=load_review_kickoff(settings.managed_dir, submitted_ids),
    )
    return follow_session(
        client, session.id, approver=deny_all, on_event=on_event, include_history=True
    )


def build_agenda(
    client: Anthropic,
    instruction: str | None,
    *,
    approver: Approver,
    on_text: Callable[[str], None] | None = None,
    on_event: EventCallback | None = None,
    settings: Settings | None = None,
    session_id: str | None = None,
) -> SessionResult:
    """Ask the chair to accept proposals and build the agenda, with a person approving.

    Pass ``session_id`` to work in an earlier agenda session instead of starting a new one.
    Anything still waiting there (a booking approval) is put to the person first. Then
    ``instruction``, if given, is sent as the organizer's reply; with no instruction this
    just re-attaches and follows the session to its end.

    # Guide 08 · Configuring your orchestrator for multi-agent · Step 4: start the session
    The roster, workflows, and advisor are all on the coordinator agent, so the session
    needs nothing extra for them. It does need what the *subagents* will use: the vault
    (Calendar OAuth, Event DB token, CloudCredits key) and the memory stores.
    """
    attach = session_id is not None
    if session_id is None:
        session_id = _start_agenda_session(client, settings or get_settings())
    return follow_session(
        client,
        session_id,
        send=[user_message(instruction)] if instruction else None,
        attach=attach,
        approver=approver,
        # Unused in phase 1. In phase 2 the perk step is a custom tool that runs here; calls
        # from subagent threads are cross-posted to this stream (Guide 20).
        custom_tools=run_custom_tool,
        on_text=on_text,
        on_event=on_event,
    )


def _start_agenda_session(client: Anthropic, settings: Settings) -> str:
    managed = ManagedResources(settings.managed_dir)
    session = client.beta.sessions.create(
        agent=managed.agent_id("program-chair"),
        environment_id=managed.environment_id(),
        title="Build the agenda",
        # Guide 07 · Passing OAuth credentials from the client to an MCP server · Step 5:
        # attach the vault. Vaults attach at session create only.
        vault_ids=[managed.vault_id()],
        resources=_chair_resources(managed),
        budget=budget(settings.agenda_budget_cents),
    )
    return session.id
