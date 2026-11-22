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


@pytest.fixture
def fresh_telemetry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No provider yet, and no repo .env leaking into the test."""
    from concierge import telemetry

    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setattr(telemetry, "_warned_unreachable", False)
    monkeypatch.setattr(telemetry, "load_otel_env", lambda env_file=None: None)
    yield


def _closed_port() -> int:
    """A local port with nothing listening on it."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_unreachable_collector_turns_tracing_off_with_one_line(
    fresh_telemetry: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from concierge.telemetry import setup_telemetry

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{_closed_port()}")

    assert setup_telemetry("test") is None
    assert setup_telemetry("test-again") is None  # serve sets up twice; still one line

    err = capsys.readouterr().err
    assert err.count("Tracing is off for this run") == 1
    assert "docker compose up -d" in err


def test_reachable_collector_registers_a_provider(
    fresh_telemetry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    from concierge import telemetry

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{port}")
        monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: None)

        provider = telemetry.setup_telemetry("test")

    assert provider is not None
    provider.shutdown()


def test_otel_sdk_disabled_turns_tracing_off(
    fresh_telemetry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concierge.telemetry import otel_endpoint

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    assert otel_endpoint() is None
