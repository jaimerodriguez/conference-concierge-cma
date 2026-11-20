"""The proposal pipeline: moderate (when needed), write the abstract, save the proposal.

A person either lets the Abstract Writer draft the proposal from a topic, or writes their own
title and abstract. Both paths end in the same stored proposal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic

from concierge.abstracts import write_abstract
from concierge.catalog import get_catalog
from concierge.config import Settings, get_settings
from concierge.moderation import FRIENDLY_REJECTION, moderate_abstract, moderate_topic
from concierge.services.store import Store
from concierge.telemetry import get_tracer

MAX_EMAIL_CHARS = 254  # the longest address SMTP allows
# Deliberately loose: one @, no spaces, and a dot in the domain. Real validation is sending mail.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.]{2,}")

RECEIVED = "Your proposal is in. The Program Chair reviews new proposals every morning."


def normalize_email(value: str) -> str | None:
    """The address, trimmed with its domain lowercased, or None when it is not an address."""
    value = value.strip()
    if len(value) > MAX_EMAIL_CHARS or not _EMAIL.fullmatch(value):
        return None
    local, domain = value.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


@dataclass(frozen=True)
class ProposalOutcome:
    accepted_for_review: bool
    message: str
    proposal: dict[str, Any] | None = None
    suggestion: str | None = None
    session_id: str | None = None


def submit_proposal(
    client: Anthropic,
    store: Store,
    *,
    contact_email: str,
    persona_id: str,
    track_id: str,
    topic: str = "",
    title: str | None = None,
    abstract: str | None = None,
    settings: Settings | None = None,
) -> ProposalOutcome:
    """Turn a persona + topic + track into a stored proposal.

    Predefined topics skip moderation; anything typed by a person is screened first. Pass
    ``title`` and ``abstract`` to save the person's own text instead of writing one.
    """
    email = normalize_email(contact_email)
    if email is None:
        return ProposalOutcome(accepted_for_review=False, message="Please enter a valid email.")
    if abstract is not None:
        return _submit_own_abstract(
            client,
            store,
            contact_email=email,
            persona_id=persona_id,
            track_id=track_id,
            title=title or "",
            abstract=abstract,
        )

    settings = settings or get_settings()
    catalog = get_catalog()
    persona = catalog.persona(persona_id)
    track = catalog.track(track_id)
    topic = topic.strip()
    predefined = topic in catalog.topics

    # Guide 05 · Wiring up OpenTelemetry · Step 4: wrap a whole operation in your own span.
    # The SDK's spans (and, with API tracing on, Anthropic's server-side spans) nest under
    # it, so one trace shows moderation, the session, and every model request inside it.
    with get_tracer().start_as_current_span("concierge.submit_proposal") as span:
        span.set_attribute("concierge.track", track.id)
        span.set_attribute("concierge.topic_predefined", predefined)

        if not predefined:
            # Guide 13 · Moderating user input · Step 1: screen typed input before any agent.
            verdict = moderate_topic(client, topic)
            span.set_attribute("concierge.moderation_allowed", verdict.allowed)
            if not verdict.allowed:
                return ProposalOutcome(
                    accepted_for_review=False,
                    message=verdict.reason or FRIENDLY_REJECTION,
                    suggestion=verdict.suggestion,
                )

        run = write_abstract(client, persona=persona, track=track, topic=topic, settings=settings)
        if run.abstract is None:
            return ProposalOutcome(
                accepted_for_review=False,
                message="The abstract writer did not finish. Please try again.",
                session_id=run.session.session_id,
            )

        member = store.find_or_add_member(email, persona=persona.id)
        proposal = store.add_proposal(
            member_id=member["id"],
            event_id=catalog.event.id,
            track=track.id,
            format=run.abstract.format,
            title=run.abstract.title,
            abstract=run.abstract.abstract,
            source="predefined_topic" if predefined else "custom_topic",
        )
        return ProposalOutcome(
            accepted_for_review=True,
            message=RECEIVED,
            proposal=proposal,
            session_id=run.session.session_id,
        )


def _submit_own_abstract(
    client: Anthropic,
    store: Store,
    *,
    contact_email: str,
    persona_id: str,
    track_id: str,
    title: str,
    abstract: str,
) -> ProposalOutcome:
    """Screen a title and abstract the person wrote, then store them as they are."""
    catalog = get_catalog()
    persona = catalog.persona(persona_id)
    track = catalog.track(track_id)
    title, abstract = title.strip(), abstract.strip()

    with get_tracer().start_as_current_span("concierge.submit_proposal") as span:
        span.set_attribute("concierge.track", track.id)
        span.set_attribute("concierge.abstract_source", "manual")

        # Everything a person types is screened, and an abstract is all typed text.
        verdict = moderate_abstract(client, title, abstract)
        span.set_attribute("concierge.moderation_allowed", verdict.allowed)
        if not verdict.allowed:
            return ProposalOutcome(
                accepted_for_review=False,
                message=verdict.reason or FRIENDLY_REJECTION,
                suggestion=verdict.suggestion,
            )

        member = store.find_or_add_member(contact_email, persona=persona.id)
        proposal = store.add_proposal(
            member_id=member["id"],
            event_id=catalog.event.id,
            track=track.id,
            format=track.format,
            title=title,
            abstract=abstract,
            source="manual_abstract",
        )
        return ProposalOutcome(accepted_for_review=True, message=RECEIVED, proposal=proposal)
