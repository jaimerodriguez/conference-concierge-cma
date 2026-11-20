"""The proposal pipeline: moderate (when needed), write the abstract, save the proposal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic

from concierge.abstracts import write_abstract
from concierge.catalog import get_catalog
from concierge.config import Settings, get_settings
from concierge.moderation import FRIENDLY_REJECTION, moderate_topic
from concierge.services.store import Store
from concierge.telemetry import get_tracer


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
    member_name: str,
    persona_id: str,
    track_id: str,
    topic: str,
    settings: Settings | None = None,
) -> ProposalOutcome:
    """Turn a persona + topic + track into a stored proposal.

    Predefined topics skip moderation; anything typed by a person is screened first.
    """
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

        member = store.find_or_add_member(member_name.strip() or "Anonymous", persona=persona.id)
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
            message="Your proposal is in. The Program Chair reviews new proposals every morning.",
            proposal=proposal,
            session_id=run.session.session_id,
        )
