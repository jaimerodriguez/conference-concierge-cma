"""`concierge setup all` runs the phase 1 setup in order and stops at the first failure."""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from concierge import cli
from concierge.managed import ManagedResources


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    log: list[str] = []

    def recorder(name: str):
        return lambda *args, **kwargs: log.append(name)

    monkeypatch.setattr(cli, "setup_host", recorder("host"))
    monkeypatch.setattr(cli, "setup_memory", recorder("memory"))
    monkeypatch.setattr(cli, "setup_vault", recorder("vault"))
    monkeypatch.setattr(cli, "auth_calendar", recorder("calendar"))
    monkeypatch.setattr(cli, "setup_deployment", recorder("deployment"))
    monkeypatch.setattr(cli, "doctor", recorder("doctor"))
    monkeypatch.setattr(cli, "_client", lambda: object())
    monkeypatch.setattr(
        ManagedResources,
        "apply",
        lambda self, folders, yes=False: log.append(f"apply:{','.join(folders) or 'all'}") or 0,
    )
    monkeypatch.setattr("concierge.vaults.has_credential_for", lambda *a, **k: False)
    return log


def test_runs_every_step_in_order(calls: list[str]) -> None:
    result = CliRunner().invoke(cli.app, ["setup", "all"])
    assert result.exit_code == 0, result.output
    assert calls == [
        "host",
        "apply:agents,environments,memory_stores,vaults",
        "memory",
        "vault",
        "calendar",
        "deployment",
        "apply:all",
        "doctor",
    ]


def test_skips_the_calendar_sign_in_when_the_vault_already_has_a_token(
    calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("concierge.vaults.has_credential_for", lambda *a, **k: True)
    assert CliRunner().invoke(cli.app, ["setup", "all"]).exit_code == 0
    assert "calendar" not in calls
    calls.clear()
    assert CliRunner().invoke(cli.app, ["setup", "all", "--reauth-calendar"]).exit_code == 0
    assert "calendar" in calls


def test_stops_at_the_first_failure_and_says_where(
    calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_apply(self: ManagedResources, folders: list[str], yes: bool = False) -> int:
        calls.append("apply")
        return 1

    monkeypatch.setattr(ManagedResources, "apply", failing_apply)
    result = CliRunner().invoke(cli.app, ["setup", "all"])
    assert result.exit_code == 1
    assert calls == ["host", "apply"]  # nothing after the failed apply ran
    assert "Stopped at step 2" in result.output and "setup all" in result.output


def test_a_bad_host_stops_before_anything_is_applied(
    calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad_host(hostname: object) -> None:
        raise typer.Exit(1)

    monkeypatch.setattr(cli, "setup_host", bad_host)
    result = CliRunner().invoke(cli.app, ["setup", "all"])
    assert result.exit_code == 1 and calls == []
    assert "Stopped at step 1" in result.output
