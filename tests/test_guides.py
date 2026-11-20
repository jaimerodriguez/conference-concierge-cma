"""The task guides and the source must keep pointing at each other."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDES = ROOT / "docs" / "guides"
SOURCE_DIRS = ("src", "managed", "phase2", "docker-compose.yml")
MARKER = re.compile(r"Guide (\d\d) · (?:[^·\n]+ · )?Step (\d+)")
FIND_IT = re.compile(r"^Find it: (.+)$", re.MULTILINE)
PATH = re.compile(r"`([\w./-]+\.(?:py|md|ya?ml|cron|example))`")
SKIPPED_DIRS = {"__pycache__", ".venv"}


def _source_files() -> list[Path]:
    files: list[Path] = []
    for name in SOURCE_DIRS:
        path = ROOT / name
        candidates = [path] if path.is_file() else sorted(path.rglob("*"))
        files += [
            file
            for file in candidates
            if file.is_file() and not SKIPPED_DIRS & set(file.parts) and file.suffix != ".pyc"
        ]
    return files


def _guide(number: str) -> Path:
    matches = list(GUIDES.glob(f"{number}-*.md"))
    assert len(matches) == 1, f"expected exactly one guide numbered {number}"
    return matches[0]


def test_every_step_marker_in_the_source_is_described_in_its_guide() -> None:
    markers: set[tuple[str, str]] = set()
    for file in _source_files():
        markers.update(MARKER.findall(file.read_text(encoding="utf-8")))
    assert markers, "no step markers found"
    for number, step in sorted(markers):
        text = _guide(number).read_text(encoding="utf-8")
        assert f"**Step {step}. " in text, f"Guide {number} has no Step {step}"


def test_every_file_a_guide_points_to_exists_and_carries_the_guide_marker() -> None:
    for guide in sorted(GUIDES.glob("[0-9][0-9]-*.md")):
        number = guide.name[:2]
        for line in FIND_IT.findall(guide.read_text(encoding="utf-8")):
            for relative in PATH.findall(line):
                target = ROOT / relative
                if not target.exists():  # `worker.py` named next to its sibling's full path
                    siblings = list(ROOT.glob(f"phase2/**/{relative}"))
                    assert siblings, f"{guide.name} points to a missing file: {relative}"
                    target = siblings[0]
                assert f"Guide {number} ·" in target.read_text(encoding="utf-8"), (
                    f"{guide.name} points to {relative}, which has no 'Guide {number} ·' marker"
                )
