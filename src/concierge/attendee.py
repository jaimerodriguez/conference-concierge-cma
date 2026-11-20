"""Answer attendee questions from system-level memory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from anthropic import Anthropic

from concierge.catalog import get_catalog
from concierge.config import Settings, get_settings
from concierge.managed import ManagedResources
from concierge.sessions import SessionResult, budget, follow_session, user_message


def ask_helper(
    client: Anthropic,
    question: str,
    *,
    on_text: Callable[[str], None] | None = None,
    on_event: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
) -> SessionResult:
    """Start a session with the Attendee Helper and ask one question."""
    settings = settings or get_settings()
    managed = ManagedResources(settings.managed_dir)
    event = get_catalog().event

    # Guide 02 · Versioning an agent and pinning sessions · Step 3: latest, or pinned
    # A bare ID means "the latest version when the session is created". Naming a version
    # pins the session to a known-good configuration, which is also how you roll back.
    helper_id = managed.agent_id("attendee-helper")
    agent: Any = helper_id
    if settings.helper_agent_version is not None:
        agent = {"type": "agent", "id": helper_id, "version": settings.helper_agent_version}

    session = client.beta.sessions.create(
        agent=agent,
        environment_id=managed.environment_id(),
        title="Attendee question",
        budget=budget(settings.helper_budget_cents),
        # Guide 04 · Giving agents system-level memory · Step 4: attach stores to the session
        # Stores are mounted at /mnt/memory/<store-name>/ and can only be attached at create.
        # Attendee input must never change what the system knows, so both are read-only:
        # that also keeps a member of the public from planting notes for later sessions.
        resources=[
            {
                "type": "memory_store",
                "memory_store_id": managed.memory_store_id("venues"),
                "access": "read_only",
                "instructions": "Venue profiles. Read the event's venue before answering.",
            },
            {
                "type": "memory_store",
                "memory_store_id": managed.memory_store_id("ops-notes"),
                "access": "read_only",
                "instructions": "Recent notes from organizers about rooms, AV, and timing.",
            },
        ],
    )
    kickoff = (
        f"Event: {event.name} on {event.date}. Doors open {event.doors_open}; talks run "
        f"{event.talks_start} to {event.talks_end}. Venue file: {event.venue}.md\n\n"
        f"Attendee question: {question}"
    )
    return follow_session(
        client, session.id, send=[user_message(kickoff)], on_text=on_text, on_event=on_event
    )
