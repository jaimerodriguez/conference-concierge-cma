"""Demo data: a batch of submitted proposals so `review run` has work, and a way to clear it.

Two ways to make proposals:
- offline (the default): free and instant. Titles and abstracts come from the templates
  below, filled with the predefined personas, topics, and tracks in content/.
- generated: each abstract is written by the Abstract Writer, through the same code
  `concierge propose` uses. About a cent each.

Everything here touches only the local SQLite store. Nothing in the Anthropic workspace
(agents, vaults, memory stores, sessions, the deployment) is created or removed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from concierge.catalog import Catalog, Persona, Track
from concierge.services.store import Store

# Distinct contact emails, so every sample proposal has a recognizable speaker.
# example.com is reserved for examples: nothing is ever delivered there.
SAMPLE_EMAILS = tuple(
    f"{name}@example.com"
    for name in (
        "ada",
        "bao",
        "carmen",
        "dev",
        "elif",
        "farah",
        "gus",
        "hana",
        "ivo",
        "juno",
        "kofi",
        "lena",
    )
)

# Roughly what one generated abstract cost in earlier runs (Abstract Writer session).
GENERATE_CENTS_EACH = 1

_TITLES = {
    "ai-ml": [
        "{Topic} on a Weekend Budget",
        "What I Got Wrong About {Topic}",
        "{Topic}, From Notebook to Production",
    ],
    "community": [
        "Learning {Topic} Together: Notes From Our Study Group",
        "{Topic} for Everyone",
        "How Our Meetup Taught Itself {Topic}",
    ],
    "lightning": [
        "{Topic} in Five Minutes",
        "Five Things I Learned From {Topic}",
        "A Lightning Tour of {Topic}",
    ],
    "fun": [
        "My Unreasonable Obsession With {Topic}",
        "{Topic}: A Saturday-Morning Experiment",
        "Overengineering {Topic} for Fun",
    ],
}

_OPENERS = {
    "weekend-hacker": "I started tinkering with {topic} on a Saturday morning and never stopped.",
    "data-engineer": "I have spent too many late nights cleaning up data about {topic}.",
    "community-organizer": "Our group first came together over {topic}.",
    "curious-student": "Six months ago I knew nothing about {topic}, so I asked questions.",
    "startup-founder": "We built, broke, and rebuilt a side project around {topic}.",
}

_BODIES = {
    "talk": [
        "This talk walks through what worked, what failed, and the one change that made the "
        "biggest difference. You will leave with a short checklist you can try at home.",
        "I will share the tools, the numbers before and after, and the mistakes that cost me "
        "the most time, so you can skip them.",
        "Expect a live demo, a few honest failures, and a clear path for getting started "
        "this weekend.",
    ],
    "lightning": [
        "In five minutes I will show the setup, one surprising result, and the single tip I "
        "wish someone had told me on day one.",
        "Five minutes, one demo, and a question for the audience to vote on.",
        "A quick before-and-after, plus the one thing I would do differently.",
    ],
}


@dataclass(frozen=True)
class SamplePlan:
    """One proposal to create: who, in which voice, on what, in which track."""

    contact_email: str
    persona: Persona
    topic: str
    track: Track


def plan_samples(catalog: Catalog, count: int, seed: int | None = None) -> list[SamplePlan]:
    """Pick ``count`` varied proposals: distinct emails, mixed personas, tracks, and topics."""
    rng = random.Random(seed)
    emails = rng.sample(SAMPLE_EMAILS, k=min(count, len(SAMPLE_EMAILS)))
    while len(emails) < count:  # more proposals than emails: some speakers submit twice
        emails.append(rng.choice(SAMPLE_EMAILS))
    topics = _spread(rng, catalog.topics, count)
    tracks = _spread(rng, catalog.tracks, count)
    return [
        SamplePlan(
            contact_email=email, persona=rng.choice(catalog.personas), topic=topic, track=track
        )
        for email, topic, track in zip(emails, topics, tracks, strict=True)
    ]


def _spread[T](rng: random.Random, items: list[T], count: int) -> list[T]:
    """``count`` picks that use every item before repeating any."""
    picks: list[T] = []
    while len(picks) < count:
        batch = list(items)
        rng.shuffle(batch)
        picks.extend(batch)
    return picks[:count]


def write_offline(plan: SamplePlan, rng: random.Random) -> tuple[str, str]:
    """A title and abstract from the templates, with no model call."""
    topic = plan.topic
    template = rng.choice(_TITLES.get(plan.track.id, _TITLES["fun"]))
    title = template.format(Topic=_title_case(topic))
    opener = _OPENERS.get(plan.persona.id, "I have been exploring {topic} for a while.")
    abstract = (
        f"{opener.format(topic=_mid_sentence(topic))} {rng.choice(_BODIES[plan.track.format])}"
    )
    return title, abstract


def _title_case(text: str) -> str:
    """Capitalize each word but keep acronyms: "running models locally (RAG)" -> "Running Models
    Locally (RAG)". ``str.title`` would turn "AI" into "Ai"."""
    return " ".join(word[:1].upper() + word[1:] for word in text.split())


def _mid_sentence(text: str) -> str:
    """Lowercase the first letter for use inside a sentence, unless it starts an acronym."""
    if len(text) > 1 and text[1].isupper():
        return text
    return text[:1].lower() + text[1:]


def create_offline(
    store: Store, catalog: Catalog, count: int, seed: int | None = None
) -> list[dict[str, Any]]:
    """Create ``count`` submitted proposals from templates. Free; no API calls."""
    rng = random.Random(seed)
    created = []
    for plan in plan_samples(catalog, count, seed):
        title, abstract = write_offline(plan, rng)
        member = store.find_or_add_member(plan.contact_email, persona=plan.persona.id)
        created.append(
            store.add_proposal(
                member_id=member["id"],
                event_id=catalog.event.id,
                track=plan.track.id,
                format=plan.track.format,
                title=title,
                abstract=abstract,
                source="sample",
            )
        )
    return created
