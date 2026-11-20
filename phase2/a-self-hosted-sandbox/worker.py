"""A self-hosted sandbox worker: the agent's tools run here, in your container.

The agent loop stays on Anthropic's side. This process long-polls Anthropic's work queue
(outbound only; nothing dials in), runs each tool call locally, and posts the result back.

Run it with ``docker compose up`` from this directory (see README.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from anthropic import AsyncAnthropic
from anthropic.lib.environments import EnvironmentWorker
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

WORKDIR = os.environ.get("CONCIERGE_WORKDIR", "/workspace")


def setup_tracing() -> TracerProvider | None:
    """Guide 20 · Moving tools into your own sandbox · Step 5: tool spans now come from here

    Anthropic emits no tool spans for tools your sandbox runs. The SDK worker emits them in
    this process, under one ``anthropic.environment.work`` span per work item, once a tracer
    provider is registered.
    """
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": "concierge-worker"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


async def main() -> None:
    provider = setup_tracing()
    # Guide 20 · Step 2: the worker authenticates with an ENVIRONMENT key, not your API key.
    # It grants access to this one environment's work queue only. Never put
    # ANTHROPIC_API_KEY on the worker host: agent tool calls could read it.
    environment_key = os.environ["ANTHROPIC_ENVIRONMENT_KEY"]
    environment_id = os.environ["ANTHROPIC_ENVIRONMENT_ID"]

    async with AsyncAnthropic(auth_token=environment_key) as client:
        worker = EnvironmentWorker(
            client,
            environment_id=environment_id,
            environment_key=environment_key,
            workdir=WORKDIR,
        )
        task = asyncio.create_task(worker.run())

        # The worker installs no signal handlers. Cancel the task (do not kill the process)
        # so it stops in-flight work and uploads changed memory files before exiting.
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, task.cancel)
        with contextlib.suppress(asyncio.CancelledError):
            await task

    if provider is not None:
        provider.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
