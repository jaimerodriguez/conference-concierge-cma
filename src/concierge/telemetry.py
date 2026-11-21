"""OpenTelemetry setup for every process in the demo.

Two independent sources of spans exist (see docs/guides/05-wiring-up-opentelemetry.md):

* **SDK tracing** (this file): the Claude SDK emits spans in *this* process and our exporter
  sends them to your backend
  (Jaeger, locally).
* **API tracing**: Anthropic emits server-side spans (model requests, agent turns, tool runs)
  to a destination an organization admin adds. No code; the guide covers it.

When both are on, the API's spans nest under the SDK's span of the same request.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None


def load_otel_env(env_file: Path | None = None) -> None:
    """Copy ``OTEL_*`` variables from the repo's ``.env`` into the process environment.

    The OpenTelemetry exporter reads only the process environment, while the demo's own
    settings (``CONCIERGE_*``) come from ``.env``. Copying the standard ``OTEL_*`` variables
    (endpoint, headers, and the rest) lets them live in ``.env`` too. A variable already set
    in the shell wins, so ``export`` still overrides the file.
    """
    from dotenv import dotenv_values

    from concierge.config import REPO_ROOT

    path = env_file if env_file is not None else REPO_ROOT / ".env"
    if not path.is_file():
        return
    for key, value in dotenv_values(path).items():
        if key.startswith("OTEL_") and value is not None and key not in os.environ:
            os.environ[key] = value


def setup_telemetry(service_name: str) -> TracerProvider | None:
    """Register a tracer provider once per process. Returns ``None`` when tracing is off.

    Tracing is on when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, in ``.env`` or the shell (for
    example to the Jaeger in ``docker-compose.yml``).
    """
    global _provider
    if _provider is not None:
        return _provider
    load_otel_env()
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None

    # Guide 05 · Wiring up OpenTelemetry · Step 2: register the tracer provider.
    # This must happen before the first Claude SDK call that should be traced.
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # The exporter reads OTEL_EXPORTER_OTLP_ENDPOINT (and optional headers) from the environment.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def sdk_telemetry_option(content_mode: str) -> dict[str, Any] | None:
    """Build the Claude SDK's ``open_telemetry`` client option.

    # Guide 05 · Wiring up OpenTelemetry · Step 3: tell the SDK which provider to use
    ``content_mode`` is ``metadata_only`` (default: IDs, timing, token counts) or ``content``
    (also prompts and responses; read the guide's warning before turning it on).
    """
    if _provider is None:
        return None
    return {"tracer_provider": _provider, "traces": {"content_mode": content_mode}}


def get_tracer() -> trace.Tracer:
    """Tracer for our own spans. Without a registered provider these are no-ops."""
    return trace.get_tracer("concierge")


def shutdown_telemetry() -> None:
    """Flush pending spans. Call before a short-lived process exits."""
    if _provider is not None:
        _provider.shutdown()
