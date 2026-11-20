"""Create an agent from code at runtime, once, and reuse it.

This is the second way to get an agent "on the fly" (the first is per-session overrides in
``abstracts.py``). Use it when your application must provision agents itself, for example
one per customer. The rule that makes it safe: create in a guarded setup step and persist
the ID. Never call ``agents.create`` on every request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from anthropic import Anthropic

from concierge.config import Settings, get_settings
from concierge.managed import ManagedResources
from concierge.sessions import SessionResult, budget, follow_session, user_message
from concierge.state import load_state, update_state

BIO_WRITER_NAME = "speaker-bio-writer"
_STATE_KEY = "bio_writer_agent_id"

BIO_WRITER_SYSTEM = """\
You write a short speaker bio for a friendly local user-group meetup.
Use only the facts you are given. Never invent employers, degrees, or awards.
Write exactly three sentences in the third person, warm and plain. Reply with the bio only.
"""


def ensure_bio_writer(client: Anthropic, settings: Settings | None = None) -> str:
    """Return the Bio Writer's agent ID, creating the agent on first use.

    # Guide 03 · Creating an agent on the fly · Step 3: create at runtime, guarded
    """
    settings = settings or get_settings()
    agent_id = load_state(settings.state_path).get(_STATE_KEY)
    if agent_id:
        return agent_id

    # Guide 03 · Step 4: the local state file may be gone, so look for the agent by name
    # before creating a duplicate.
    for agent in client.beta.agents.list():
        if agent.name == BIO_WRITER_NAME:
            update_state(settings.state_path, **{_STATE_KEY: agent.id})
            return agent.id

    agent = client.beta.agents.create(
        name=BIO_WRITER_NAME,
        description="Writes a three-sentence bio for an accepted speaker.",
        model="claude-haiku-5-5",
        system=BIO_WRITER_SYSTEM,
        # No tools: this agent only writes text. A simple agent gets no multiagent block.
        tools=[],
    )
    # Guide 03 · Step 5: persist the ID so the next run reuses the same agent.
    update_state(settings.state_path, **{_STATE_KEY: agent.id})
    return agent.id


def write_bio(
    client: Anthropic,
    *,
    name: str,
    facts: str,
    on_event: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
) -> SessionResult:
    """Run one session that writes a bio. ``result.text`` holds the bio."""
    settings = settings or get_settings()
    session = client.beta.sessions.create(
        agent=ensure_bio_writer(client, settings),
        environment_id=ManagedResources(settings.managed_dir).environment_id(),
        title=f"Bio: {name}",
        budget=budget(settings.helper_budget_cents),
    )
    return follow_session(
        client,
        session.id,
        send=[user_message(f"Speaker: {name}\nFacts the speaker gave us: {facts}")],
        on_event=on_event,
    )
