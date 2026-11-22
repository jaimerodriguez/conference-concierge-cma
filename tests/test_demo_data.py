"""Demo data: clear only what runs create; sample proposals are varied and free by default."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from typer.testing import CliRunner

from concierge import cli
from concierge.catalog import load_catalog
from concierge.config import REPO_ROOT, Settings
from concierge.moderation import MAX_ABSTRACT_CHARS, MAX_TITLE_CHARS
from concierge.sample_data import MAX_SAMPLES, create_offline, load_samples
from concierge.services.store import Store

CATALOG = load_catalog(REPO_ROOT / "content")
SAMPLES = load_samples(REPO_ROOT / "content")


@pytest.fixture
def store(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Store:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "shutdown_telemetry", lambda: None)
    monkeypatch.setattr(cli, "_client", lambda: pytest.fail("no API calls in these tests"))
    return Store(settings.db_path)


def _fill(store: Store) -> None:
    proposal = create_offline(store, CATALOG, SAMPLES[:2])[0]
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
    result = CliRunner().invoke(cli.app, ["data", "sample"])
    assert result.exit_code == 0, result.output
    assert "no cost" in result.output
    proposals = store.list_proposals(status="submitted")
    assert len(proposals) == MAX_SAMPLES
    emails = {store.get_member(p["member_id"])["contact_email"] for p in proposals}  # type: ignore[index]
    assert len(emails) == MAX_SAMPLES  # one distinct speaker per proposal
    assert all(email.endswith("@example.com") for email in emails)
    assert len({p["track"] for p in proposals}) == len(CATALOG.tracks)  # every track used
    full = [store.get_proposal(p["id"]) for p in proposals]
    assert all(p and p["title"] and p["abstract"] and p["source"] == "sample" for p in full)
    assert "injection" in result.output  # the Case column is printed


def test_sample_cases_are_never_saved(store: Store) -> None:
    CliRunner().invoke(cli.app, ["data", "sample"])
    saved = " ".join(
        f"{p['title']} {p['abstract']}"  # type: ignore[index]
        for p in (store.get_proposal(row["id"]) for row in store.list_proposals())
    )
    assert all(sample.expect not in saved for sample in SAMPLES)


def test_sample_set_has_accurate_proposals_first_then_the_problem_cases() -> None:
    cases = [sample.case for sample in SAMPLES]
    assert 8 <= len(cases) <= MAX_SAMPLES
    assert cases[:5] == ["accurate"] * 5 and "accurate" not in cases[5:]
    for needed in ("title does not match abstract", "inappropriate content"):
        assert needed in cases[5:7]  # the two the demo must show, kept by --count 7


def test_sample_proposals_fit_the_limits_and_the_catalog() -> None:
    for sample in SAMPLES:
        CATALOG.persona(sample.persona), CATALOG.track(sample.track)  # raise when unknown
        assert len(sample.title) <= MAX_TITLE_CHARS
        assert len(sample.abstract) <= MAX_ABSTRACT_CHARS
        if sample.accurate:  # the base rubric's length criterion
            assert 60 <= len(sample.abstract.split()) <= 120, sample.title


def test_sample_count_takes_from_the_top_and_stops_at_ten(store: Store) -> None:
    result = CliRunner().invoke(cli.app, ["data", "sample", "--count", "3"])
    assert result.exit_code == 0, result.output
    titles = [p["title"] for p in store.list_proposals()]
    assert sorted(titles) == sorted(s.title for s in SAMPLES[:3])
    too_many = CliRunner().invoke(cli.app, ["data", "sample", "--count", "11"])
    assert too_many.exit_code != 0


def test_sample_generate_states_the_cost_and_asks(store: Store) -> None:
    result = CliRunner().invoke(
        cli.app, ["data", "sample", "--generate", "--count", "3"], input="n\n"
    )
    assert result.exit_code == 1
    assert "$0.03" in result.output and "Nothing created" in result.output
    assert store.list_proposals() == []


def test_sample_generate_writes_accurate_abstracts_and_screens_the_problem_cases(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_submit(client, store, *, contact_email, persona_id, track_id, title, abstract):  # type: ignore[no-untyped-def]
        calls.append((contact_email, abstract))
        if abstract and "damn" in abstract:  # moderation stops the inappropriate one
            return NS(proposal=None, message="Let's keep it friendly.")
        member = store.find_or_add_member(contact_email, persona=persona_id)
        proposal = store.add_proposal(
            member_id=member["id"],
            event_id="e",
            track=track_id,
            format="talk",
            title=title,
            abstract=abstract or "...",
            source="manual_abstract" if abstract else "ai_abstract",
        )
        return NS(proposal=proposal, message="in")

    monkeypatch.setattr(cli, "_client", lambda: object())
    monkeypatch.setattr("concierge.proposals.submit_proposal", fake_submit)
    result = CliRunner().invoke(cli.app, ["data", "sample", "--generate", "--count", "7", "--yes"])
    assert result.exit_code == 0, result.output
    assert [abstract is None for _, abstract in calls] == [True] * 5 + [False] * 2
    assert "Moderation stopped" in result.output and "inappropriate content" in result.output
    assert len(store.list_proposals(status="submitted")) == 6


def test_a_second_proposal_reuses_the_member_with_that_email(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = Store(tmp_path / "db.sqlite")
    first = store.find_or_add_member("priya@example.com", persona="data-engineer")
    again = store.find_or_add_member(" Priya@Example.com ", persona="weekend-hacker")
    assert again["id"] == first["id"]
    assert len(store.list_members()) == 1
    assert store.find_or_add_member("sam@example.com")["id"] != first["id"]


def test_an_old_database_with_first_names_is_migrated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sqlite3

    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE members (id TEXT PRIMARY KEY, name TEXT NOT NULL, persona TEXT,"
            " roles TEXT NOT NULL DEFAULT '[\"attendee\"]', created_at REAL NOT NULL)"
        )
        db.execute("INSERT INTO members (id, name, created_at) VALUES ('mem_1', 'Ada', 0)")
        db.execute("INSERT INTO members (id, name, created_at) VALUES ('mem_2', 'b@x.org', 0)")
    store = Store(path)
    assert store.get_member("mem_1")["contact_email"] == "ada@example.com"  # type: ignore[index]
    assert store.get_member("mem_2")["contact_email"] == "b@x.org"  # type: ignore[index]
    Store(path)  # migrating twice is a no-op


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
