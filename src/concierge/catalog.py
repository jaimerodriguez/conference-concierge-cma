"""Load the demo's static content: personas, tracks, and the event."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from concierge.config import get_settings

TalkFormat = Literal["talk", "lightning"]


class Persona(BaseModel):
    id: str
    name: str
    voice: str


class Track(BaseModel):
    id: str
    name: str
    format: TalkFormat


class Slots(BaseModel):
    talk_minutes: int
    lightning_minutes: int
    break_minutes: int
    # Kept free before the end of the evening, because talks run over (see ops-notes).
    buffer_minutes: int = 10


class Event(BaseModel):
    id: str
    name: str
    date: str
    doors_open: str
    talks_start: str
    talks_end: str
    venue: str
    slots: Slots


class Catalog(BaseModel):
    personas: list[Persona]
    tracks: list[Track]
    event: Event

    def persona(self, persona_id: str) -> Persona:
        return _find(self.personas, persona_id, "persona")

    def track(self, track_id: str) -> Track:
        return _find(self.tracks, track_id, "track")


def _find[T: (Persona, Track)](items: list[T], item_id: str, kind: str) -> T:
    for item in items:
        if item.id == item_id:
            return item
    known = ", ".join(item.id for item in items)
    raise KeyError(f"Unknown {kind} {item_id!r}. Known: {known}")


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_catalog(content_dir: Path) -> Catalog:
    return Catalog.model_validate(
        {
            "personas": _load_yaml(content_dir / "personas.yaml"),
            "tracks": _load_yaml(content_dir / "tracks.yaml"),
            "event": _load_yaml(content_dir / "event.yaml"),
        }
    )


@lru_cache
def get_catalog() -> Catalog:
    return load_catalog(get_settings().content_dir)


def rubric_for_track(content_dir: Path, track_id: str) -> str:
    """Compose the templated rubric: the shared base plus the track's own criteria.

    Adding a track means adding one file under ``content/rubrics/tracks/``.
    """
    rubrics = content_dir / "rubrics"
    base = (rubrics / "base.md").read_text(encoding="utf-8")
    track = (rubrics / "tracks" / f"{track_id}.md").read_text(encoding="utf-8")
    return f"{base.rstrip()}\n\n{track.rstrip()}\n"
