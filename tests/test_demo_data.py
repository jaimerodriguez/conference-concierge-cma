"""Demo data: clear only what runs create; sample proposals are varied and free by default."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from typer.testing import CliRunner

from concierge import cli
from concierge.catalog import load_catalog
from concierge.config import REPO_ROOT, Settings
from concierge.sample_data import create_offline, plan_samples
from concierge.services.store import Store

CATALOG = load_catalog(REPO_ROOT / "content")


@pytest.fixture
def store(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Store:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "shutdown_telemetry", lambda: None)
    monkeypatch.setattr(cli, "_client", lambda: pytest.fail("no API calls in these tests"))
    return Store(settings.db_path)


def _fill(store: Store) -> None:
    proposal = create_offline(store, CATALOG, 2, seed=1)[0]
    store.record_review(
        proposal["id"], scores={"Respectful": 5}, overall=4.0, recommendation="accept", summary="ok"
    )
    store.add_calendar_event(
        title="Talk", room="Main Hall", starts_at="18:30", ends_at="18:55", created_by="organizer"
    )
    store.issue_perk(proposal["member_id"], 25)
    store.save_oauth_token(
        token="t",
        kind="access",
        client_id="c",
        scope="calendar",
        subject="organizer",
        expires_at=None,
    )


def test_clear_asks_first_and_keeps_the_calendar_sign_in(store: Store) -> None:
    _fill(store)
    refused = CliRunner().invoke(cli.app, ["data", "clear", "--local-only"], input="n\n")
    assert refused.exit_code == 1 and "Nothing deleted" in refused.output
    assert store.demo_data_counts()["proposals"] == 2
    assert "Skipped (--local-only)" in refused.output and "proposals" in refused.output

    done = CliRunner().invoke(cli.app, ["data", "clear", "--yes", "--local-only"])
    assert done.exit_code == 0, done.output
    assert not any(store.demo_data_counts().values())
    assert store.get_oauth_token("t", "access") is not None  # the vault's sign-in still works
    again = CliRunner().invoke(cli.app, ["data", "clear", "--local-only"])
    assert "already empty" in again.output and "Nothing to clear" in again.output


def test_sample_offline_is_free_varied_and_submitted(store: Store) -> None:
    result = CliRunner().invoke(cli.app, ["data", "sample", "--seed", "7"])
    assert result.exit_code == 0, result.output
    assert "no cost" in result.output
    proposals = store.list_proposals(status="submitted")
    assert len(proposals) == 8
    names = {store.get_member(p["member_id"])["name"] for p in proposals}  # type: ignore[index]
    assert len(names) == 8  # one distinct speaker per proposal
    assert len({p["track"] for p in proposals}) == len(CATALOG.tracks)  # every track used
    full = [store.get_proposal(p["id"]) for p in proposals]
    assert all(p and p["title"] and p["abstract"] and p["source"] == "sample" for p in full)


def test_sample_plans_repeat_with_a_seed() -> None:
    first = [(p.name, p.topic, p.track.id) for p in plan_samples(CATALOG, 8, seed=3)]
    assert first == [(p.name, p.topic, p.track.id) for p in plan_samples(CATALOG, 8, seed=3)]


def test_sample_generate_states_the_cost_and_asks(store: Store) -> None:
    result = CliRunner().invoke(
        cli.app, ["data", "sample", "--generate", "--count", "3"], input="n\n"
    )
    assert result.exit_code == 1
    assert "$0.03" in result.output and "Nothing created" in result.output
    assert store.list_proposals() == []


def test_sample_generate_uses_the_propose_path(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_submit(client, store, *, member_name, persona_id, track_id, topic):  # type: ignore[no-untyped-def]
        calls.append(member_name)
        member = store.find_or_add_member(member_name, persona=persona_id)
        proposal = store.add_proposal(
            member_id=member["id"],
            event_id="e",
            track=track_id,
            format="talk",
            title=f"About {topic}",
            abstract="...",
            source="predefined_topic",
        )
        return NS(proposal=proposal, message="in")

    monkeypatch.setattr(cli, "_client", lambda: object())
    monkeypatch.setattr("concierge.proposals.submit_proposal", fake_submit)
    result = CliRunner().invoke(cli.app, ["data", "sample", "--generate", "--count", "2", "--yes"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 2 and len(store.list_proposals(status="submitted")) == 2


def test_a_second_proposal_reuses_the_member_with_that_name(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = Store(tmp_path / "db.sqlite")
    first = store.find_or_add_member("Priya", persona="data-engineer")
    again = store.find_or_add_member(" priya ", persona="weekend-hacker")
    assert again["id"] == first["id"]
    assert len(store.list_members()) == 1
    assert store.find_or_add_member("Sam")["id"] != first["id"]


class FakeMemories:
    """Stand-in for client.beta.memory_stores.memories: one store, in memory."""

    def __init__(self, notes: dict[str, str]) -> None:
        self.notes = {path: (f"m{i}", text) for i, (path, text) in enumerate(notes.items())}
        self.deleted: list[str] = []

    def list(self, store_id: str, path_prefix: str = "/") -> list[NS]:
        return [NS(path=p, id=i, type="memory") for p, (i, _) in self.notes.items()]

    def retrieve(self, memory_id: str, memory_store_id: str) -> NS:
        text = next(t for i, t in self.notes.values() if i == memory_id)
        return NS(content=text, content_sha256="sha")

    def delete(self, memory_id: str, memory_store_id: str) -> None:
        self.deleted.append(memory_id)
        self.notes = {p: v for p, v in self.notes.items() if v[0] != memory_id}

    def create(self, store_id: str, path: str, content: str) -> None:
        self.notes[path] = (f"new{len(self.notes)}", content)

    def update(
        self, memory_id: str, memory_store_id: str, content: str, precondition: object
    ) -> None:
        path = next(p for p, (i, _) in self.notes.items() if i == memory_id)
        self.notes[path] = (memory_id, content)


@pytest.fixture
def memories(store: Store, monkeypatch: pytest.MonkeyPatch) -> FakeMemories:
    seed = (REPO_ROOT / "content" / "ops-notes" / "README.md").read_text(encoding="utf-8")
    fake = FakeMemories(
        {"/README.md": seed + "an agent edited this", "/2026-12-10-run-note.md": "learned"}
    )
    client = NS(beta=NS(memory_stores=NS(memories=fake)))
    monkeypatch.setattr(cli, "_client", lambda: client)
    monkeypatch.setattr(cli.ManagedResources, "memory_store_id", lambda self, name: "memstore_x")
    return fake


def test_clear_resets_the_ops_notes_memory_and_names_what_it_deletes(
    store: Store, memories: FakeMemories
) -> None:
    _fill(store)
    refused = CliRunner().invoke(cli.app, ["data", "clear"], input="n\n")
    assert refused.exit_code == 1, refused.output
    assert "permanently deletes" in refused.output and "/2026-12-10-run-note.md" in refused.output
    assert "restores from content/ops-notes: /README.md" in refused.output
    assert "rubrics and venues memory" in refused.output
    assert memories.deleted == [] and store.demo_data_counts()["proposals"] == 2

    done = CliRunner().invoke(cli.app, ["data", "clear", "--yes"])
    assert done.exit_code == 0, done.output
    assert set(memories.notes) == {"/README.md"}  # run note gone, seed restored
    assert memories.notes["/README.md"][1].endswith("an agent edited this") is False
    assert "ops-notes reset" in done.output and not any(store.demo_data_counts().values())


def test_clear_still_clears_locally_when_the_api_is_unreachable(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fill(store)

    def unreachable() -> object:
        raise ConnectionError("no network")

    monkeypatch.setattr(cli, "_client", unreachable)
    result = CliRunner().invoke(cli.app, ["data", "clear", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Could not read the ops-notes memory store" in result.output
    assert "notes will not be reset" in result.output
    assert not any(store.demo_data_counts().values())
