"""`concierge propose` offers the portal's choices and runs the portal's checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest
from typer.testing import CliRunner

from concierge import cli
from concierge.catalog import load_catalog
from concierge.config import REPO_ROOT
from concierge.proposals import MIN_ABSTRACT_CHARS, check_submission

CATALOG = load_catalog(REPO_ROOT / "content")
OWN_ABSTRACT = "We distill a large model into a small one and run it on a laptop, live on stage."
GOOD = {
    "contact_email": "sam@example.com",
    "title": "Distilling a big model",
    "track_id": "fun",
    "persona_id": "weekend-hacker",
}


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({}, None),
        ({"abstract": OWN_ABSTRACT}, None),
        ({"contact_email": "sam@"}, "valid contact email"),
        ({"title": "  "}, "title"),
        ({"abstract": "too short"}, f"at least {MIN_ABSTRACT_CHARS}"),
        ({"abstract": "x" * 2000}, "under"),
        ({"track_id": "nope"}, "tracks"),
        ({"persona_id": "nope"}, "personas"),
    ],
)
def test_check_submission(changes: dict[str, Any], problem: str | None) -> None:
    found = check_submission(CATALOG, **{**GOOD, **changes})
    assert found is None if problem is None else problem in found


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    """Record what `propose` hands to the pipeline instead of calling Claude."""
    calls: list[dict[str, Any]] = []

    def fake_submit(client, store, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        abstract = kwargs["abstract"] or "Written by the agent."
        proposal = {"id": "p1", "title": kwargs["title"], "abstract": abstract}
        return NS(
            accepted_for_review=True,
            proposal=proposal,
            message="Your proposal is in.",
            suggestion=None,
            session_id=None,
        )

    monkeypatch.setattr(cli, "_client", lambda: object())
    monkeypatch.setattr("concierge.proposals.submit_proposal", fake_submit)
    return calls


def test_propose_lets_ai_write_the_abstract_by_default(submitted: list[dict[str, Any]]) -> None:
    result = CliRunner().invoke(cli.app, ["propose", "Distilling a big model"])
    assert result.exit_code == 0, result.output
    assert submitted[0]["abstract"] is None


def test_propose_takes_your_own_abstract(submitted: list[dict[str, Any]], tmp_path: Path) -> None:
    typed = CliRunner().invoke(cli.app, ["propose", "Distill", "--abstract", OWN_ABSTRACT])
    assert typed.exit_code == 0, typed.output
    assert OWN_ABSTRACT in typed.output

    path = tmp_path / "abstract.md"
    path.write_text(OWN_ABSTRACT + "\n", encoding="utf-8")
    from_file = CliRunner().invoke(cli.app, ["propose", "Distill", "--abstract-file", str(path)])
    piped = CliRunner().invoke(
        cli.app, ["propose", "Distill", "--abstract-file", "-"], input=OWN_ABSTRACT
    )
    assert from_file.exit_code == 0, from_file.output
    assert piped.exit_code == 0, piped.output
    assert [call["abstract"].strip() for call in submitted] == [OWN_ABSTRACT] * 3


def test_propose_rejects_bad_input_before_any_model_call(submitted: list[dict[str, Any]]) -> None:
    runner = CliRunner()
    short = runner.invoke(cli.app, ["propose", "Distill", "--abstract", "too short"])
    assert short.exit_code == 1 and "at least" in short.output
    unknown = runner.invoke(cli.app, ["propose", "Distill", "--track", "nope"])
    assert unknown.exit_code == 1 and "tracks" in unknown.output
    both = runner.invoke(
        cli.app, ["propose", "Distill", "--abstract", OWN_ABSTRACT, "--abstract-file", "-"]
    )
    assert both.exit_code == 2
    assert submitted == []
