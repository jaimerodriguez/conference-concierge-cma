"""Demo data: a batch of submitted proposals so `review run` has work, and a way to clear it.

The proposals live in ``content/sample_proposals.yaml``: five solid ones, then deliberate
problem cases (a title that does not match its abstract, inappropriate content, a prompt
injection, a sales pitch, a workshop squeezed into a lightning slot). Each problem case fails
one thing the review process checks, so the demo shows the process catching it.

Two ways to add them:
- offline (the default): free and instant. Every proposal is saved as written, straight into
  the Event DB, so even the inappropriate one reaches the CFP Reviewers. That shows the
  second line of defense: the "Respectful" criterion declines it and the digest names it.
- generated: the accurate proposals get their abstract from the Abstract Writer, through the
  same code `concierge propose` uses. The problem cases keep their own abstracts and go
  through the "write my own abstract" path, so moderation screens them first and stops the
  ones that cross the line: the front door.

Everything here touches only the local SQLite store. Nothing in the Anthropic workspace
(agents, vaults, memory stores, sessions, the deployment) is created or removed.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from concierge.catalog import Catalog
from concierge.config import get_settings
from concierge.services.store import Store

SAMPLE_FILE = "sample_proposals.yaml"
MAX_SAMPLES = 10
ACCURATE = "accurate"

# Roughly what one generated abstract cost in earlier runs (Abstract Writer session).
GENERATE_CENTS_EACH = 1


class SampleProposal(BaseModel):
    """One sample proposal, and what the review process should do with it.

    ``case`` and ``expect`` are for the presenter only. They are never saved, so the
    reviewers judge the proposal on its title and abstract alone.
    """

    case: str
    expect: str
    contact_email: str
    persona: str
    track: str
    title: str
    abstract: str

    @property
    def accurate(self) -> bool:
        return self.case == ACCURATE


def load_samples(content_dir: Path) -> list[SampleProposal]:
    raw = yaml.safe_load((content_dir / SAMPLE_FILE).read_text(encoding="utf-8"))
    samples = [SampleProposal.model_validate(item) for item in raw]
    if len(samples) > MAX_SAMPLES:
        raise ValueError(f"{SAMPLE_FILE} has {len(samples)} proposals; keep it to {MAX_SAMPLES}.")
    return samples


@lru_cache
def get_samples() -> list[SampleProposal]:
    return load_samples(get_settings().content_dir)


def pick_samples(samples: list[SampleProposal], count: int) -> list[SampleProposal]:
    """The first ``count`` samples: the accurate ones come first in the file."""
    return samples[:count]


def create_offline(
    store: Store, catalog: Catalog, samples: list[SampleProposal]
) -> list[dict[str, Any]]:
    """Save the samples as written, status "submitted". Free; no API calls, no moderation."""
    created = []
    for sample in samples:
        track = catalog.track(sample.track)
        member = store.find_or_add_member(
            sample.contact_email, persona=catalog.persona(sample.persona).id
        )
        created.append(
            store.add_proposal(
                member_id=member["id"],
                event_id=catalog.event.id,
                track=track.id,
                format=track.format,
                title=sample.title,
                abstract=sample.abstract,
                source="sample",
            )
        )
    return created
