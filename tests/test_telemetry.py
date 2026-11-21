"""OpenTelemetry settings can live in .env, and the shell still wins."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from concierge.telemetry import load_otel_env


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def test_otel_variables_are_read_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318\n"
        "OTEL_EXPORTER_OTLP_HEADERS=x-api-key=from-file\n"
        "CONCIERGE_OTEL_CONTENT_MODE=content\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    monkeypatch.delenv("CONCIERGE_OTEL_CONTENT_MODE", raising=False)

    load_otel_env(env_file)

    assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4318"
    assert os.environ["OTEL_EXPORTER_OTLP_HEADERS"] == "x-api-key=from-file"
    # Only OTEL_* is copied; CONCIERGE_* stays with the settings class.
    assert "CONCIERGE_OTEL_CONTENT_MODE" not in os.environ


def test_shell_export_wins_over_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OTEL_EXPORTER_OTLP_ENDPOINT=http://from-file:4318\n", encoding="utf-8")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://from-shell:4318")

    load_otel_env(env_file)

    assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://from-shell:4318"


def test_missing_env_file_is_fine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    load_otel_env(tmp_path / "nope.env")

    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ
