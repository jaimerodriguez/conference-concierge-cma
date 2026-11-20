"""Write a talk abstract with an agent configured on the fly.

Every session needs a stored agent, so "inline" agents come in two flavors:

* **Per-session overrides** (this file): keep one stored base agent and replace parts of its
  configuration for a single session. No new agent, no new version.
* **Runtime creation** (``bios.py``): call ``agents.create`` from code, once, and reuse the ID.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from concierge.catalog import Persona, TalkFormat, Track, get_catalog
from concierge.config import Settings, get_settings
from concierge.managed import ManagedResources
from concierge.sessions import SessionResult, budget, follow_session, read_output_file

OUTPUT_FILE = "abstract.json"


class Abstract(BaseModel):
    title: str
    abstract: str
    format: TalkFormat


@dataclass(frozen=True)
class AbstractRun:
    abstract: Abstract | None
    session: SessionResult


def build_system_prompt(settings: Settings, persona: Persona, track: Track) -> str:
    """Fill the prompt template with this request's persona and track."""
    template = (settings.content_dir / "prompts" / "abstract_writer.md").read_text(encoding="utf-8")
    slots = get_catalog().event.slots
    minutes = slots.talk_minutes if track.format == "talk" else slots.lightning_minutes
    return template.format(
        persona_name=persona.name,
        persona_voice=persona.voice,
        track_name=track.name,
        format=track.format,
        minutes=minutes,
    )


def write_abstract(
    client: Anthropic,
    *,
    persona: Persona,
    track: Track,
    topic: str,
    settings: Settings | None = None,
) -> AbstractRun:
    """Run one short session that writes an abstract for ``topic``.

    ``topic`` must already be safe: predefined, or passed through ``moderate_topic``.
    """
    settings = settings or get_settings()
    managed = ManagedResources(settings.managed_dir)
    rubric = (settings.content_dir / "rubrics" / "abstract.md").read_text(encoding="utf-8")

    session = client.beta.sessions.create(
        # Guide 03 · Creating an agent on the fly · Step 2: override the stored agent
        # `agent_with_overrides` replaces fields for THIS session only. A field we omit
        # (model, tools) is inherited; a field we pass replaces the agent's value in full.
        agent={
            "type": "agent_with_overrides",
            "id": managed.agent_id("abstract-writer"),
            "system": build_system_prompt(settings, persona, track),
        },
        environment_id=managed.environment_id(),
        title=f"Abstract: {topic[:60]}",
        # Guide 12 · Approvals and budgets · Step 2: cap what one audience submission can spend.
        budget=budget(settings.proposal_budget_cents),
        metadata={"persona": persona.id, "track": track.id},
        # Guide 11 · Grading work with outcomes · Step 1: start with an outcome, not a message
        # The job is one checkable deliverable, so a separate grader scores each attempt
        # against the rubric and the agent revises until it passes. Passing the event in
        # `initial_events` creates the session and starts the work in one call.
        initial_events=[
            {
                "type": "user.define_outcome",
                "description": (
                    f"Write a proposal for a {track.format} about this topic: {topic!r}. "
                    f"Save it as /mnt/session/outputs/{OUTPUT_FILE}."
                ),
                "rubric": {"type": "text", "content": rubric},
                "max_iterations": 3,
            }
        ],
    )

    # The session is already running, so include what happened before our stream opened.
    result = follow_session(client, session.id, include_history=True)
    return AbstractRun(abstract=_read_abstract(client, result), session=result)


def _read_abstract(client: Anthropic, result: SessionResult) -> Abstract | None:
    """Guide 11 · Grading work with outcomes · Step 4: fetch the deliverable."""
    raw = read_output_file(client, result.session_id, OUTPUT_FILE)
    candidates = [raw.decode("utf-8")] if raw else []
    # Fallback for self-hosted setups (phase 2), where files the agent writes stay in your
    # own sandbox: the agent also replies with the same JSON, so read it from its message.
    start, end = result.text.find("{"), result.text.rfind("}")
    if start != -1 and end > start:
        candidates.append(result.text[start : end + 1])
    for candidate in candidates:
        try:
            return Abstract.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValidationError):
            continue
    return None
