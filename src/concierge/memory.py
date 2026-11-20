"""Seed the workspace's memory stores from the files under ``content/``.

The stores themselves are declared in ``managed/memory_stores/`` and created by ``ant apply``.
This module fills them. It is safe to run again: existing memories are updated in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from concierge.config import Settings, get_settings
from concierge.managed import ManagedResources

# store name -> directory under content/ whose markdown files seed it
SEED_SOURCES: dict[str, str] = {
    "venues": "venues",
    "rubrics": "rubrics",
    "ops-notes": "ops-notes",
}


@dataclass(frozen=True)
class SeedReport:
    store: str
    created: int
    updated: int
    unchanged: int


def seed_store(client: Anthropic, store_id: str, source_dir: Path, store_name: str) -> SeedReport:
    """Copy every markdown file under ``source_dir`` into the store, keeping relative paths."""
    # Guide 04 · Giving agents system-level memory · Step 2: seed reference content
    # List what is already there so a second run updates instead of failing with a 409.
    existing = {
        memory.path: memory
        for memory in client.beta.memory_stores.memories.list(store_id, path_prefix="/")
        if memory.type == "memory"
    }
    created = updated = unchanged = 0
    for file in sorted(source_dir.rglob("*.md")):
        path = "/" + file.relative_to(source_dir).as_posix()
        content = file.read_text(encoding="utf-8")
        current = existing.get(path)
        if current is None:
            client.beta.memory_stores.memories.create(store_id, path=path, content=content)
            created += 1
            continue
        stored = client.beta.memory_stores.memories.retrieve(current.id, memory_store_id=store_id)
        if stored.content == content:
            unchanged += 1
            continue
        # Guide 04 · Step 3: update safely. The precondition makes the write fail (409)
        # rather than silently overwrite a change an agent made since we read the memory.
        client.beta.memory_stores.memories.update(
            current.id,
            memory_store_id=store_id,
            content=content,
            precondition={"type": "content_sha256", "content_sha256": stored.content_sha256},
        )
        updated += 1
    return SeedReport(store=store_name, created=created, updated=updated, unchanged=unchanged)


def seed_all(client: Anthropic, settings: Settings | None = None) -> list[SeedReport]:
    settings = settings or get_settings()
    managed = ManagedResources(settings.managed_dir)
    return [
        seed_store(client, managed.memory_store_id(store), settings.content_dir / directory, store)
        for store, directory in SEED_SOURCES.items()
    ]


# The stores agents write to during runs. Only ops-notes is attached read_write (see
# _chair_resources in review.py); rubrics and venues are read_only reference material.
RUN_WRITTEN_STORES = ("ops-notes",)


@dataclass(frozen=True)
class ResetPlan:
    """What resetting a store to its seed would change. Nothing is changed by planning."""

    store: str
    store_id: str
    delete: list[tuple[str, str]]  # (path, memory id) of memories not in the seed
    restore: list[str]  # seed paths that are missing or were changed

    @property
    def empty(self) -> bool:
        return not self.delete and not self.restore


def plan_reset(client: Anthropic, store_id: str, source_dir: Path, store_name: str) -> ResetPlan:
    """Compare a store with its seed files: run-written notes to delete, seed files to restore."""
    seed = {
        "/" + file.relative_to(source_dir).as_posix(): file.read_text(encoding="utf-8")
        for file in sorted(source_dir.rglob("*.md"))
    }
    existing = {
        memory.path: memory
        for memory in client.beta.memory_stores.memories.list(store_id, path_prefix="/")
        if memory.type == "memory"
    }
    delete = sorted((path, memory.id) for path, memory in existing.items() if path not in seed)
    restore = []
    for path, content in seed.items():
        current = existing.get(path)
        if current is None:
            restore.append(path)
            continue
        stored = client.beta.memory_stores.memories.retrieve(current.id, memory_store_id=store_id)
        if stored.content != content:
            restore.append(path)
    return ResetPlan(store=store_name, store_id=store_id, delete=delete, restore=restore)


def apply_reset(client: Anthropic, plan: ResetPlan, source_dir: Path) -> SeedReport:
    """Delete the run-written notes, then put the seed files back. Permanent."""
    for _path, memory_id in plan.delete:
        client.beta.memory_stores.memories.delete(memory_id, memory_store_id=plan.store_id)
    return seed_store(client, plan.store_id, source_dir, plan.store)
