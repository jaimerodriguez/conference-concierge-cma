"""Put the sample placeholders back into the resource files, so they are safe to publish.

``concierge setup host`` writes your tunnel host into the agent and environment files, and
``concierge setup deployment`` writes your vault's ID into the deployment file. Both are
yours alone: someone who clones the repo needs the sample values back, so that
``setup host`` and ``setup deployment`` work for them too. This module finds those values
and swaps them back. ``concierge setup public`` is the command that calls it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from concierge.config import PLACEHOLDER_HOST

# Only these file types carry the host and the vault ID; claude-lock.json is git-ignored.
RESOURCE_SUFFIXES = frozenset({".md", ".yaml"})
_VAULT_ID = re.compile(r"\bvlt_[A-Za-z0-9]+")
_VAULT_IDS_LINE = re.compile(r"^vault_ids:\s*\[[^\]]*\]", re.MULTILINE)


@dataclass(frozen=True)
class Finding:
    """One private value in one file."""

    path: Path
    value: str


def resource_files(roots: Iterable[Path]) -> list[Path]:
    """Every agent, environment, store, vault and deployment file under ``roots``."""
    return sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.suffix in RESOURCE_SUFFIXES and path.is_file()
    )


def private_hosts(*candidates: str | None) -> list[str]:
    """The given hosts that are really someone's own: not empty, not the sample host."""
    hosts = {host.strip().lower() for host in candidates if host and host.strip()}
    hosts.discard(PLACEHOLDER_HOST)
    return sorted(hosts)


def find_private_values(roots: Iterable[Path], hosts: Iterable[str]) -> list[Finding]:
    """Each file that names one of ``hosts`` or holds a vault ID, with the value found."""
    hosts = list(hosts)
    findings: list[Finding] = []
    for path in resource_files(roots):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        findings += [Finding(path, host) for host in hosts if host in lowered]
        findings += [Finding(path, vault) for vault in sorted(set(_VAULT_ID.findall(text)))]
    return findings


def restore_placeholders(roots: Iterable[Path], hosts: Iterable[str]) -> list[Path]:
    """Swap ``hosts`` for the sample host and empty ``vault_ids``. Returns the changed files."""
    patterns = [re.compile(re.escape(host), re.IGNORECASE) for host in hosts]
    changed: list[Path] = []
    for path in resource_files(roots):
        text = path.read_text(encoding="utf-8")
        new = text
        for pattern in patterns:
            new = pattern.sub(PLACEHOLDER_HOST, new)
        new = _VAULT_IDS_LINE.sub(
            lambda line: "vault_ids: []" if _VAULT_ID.search(line.group(0)) else line.group(0),
            new,
        )
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(path)
    return changed
