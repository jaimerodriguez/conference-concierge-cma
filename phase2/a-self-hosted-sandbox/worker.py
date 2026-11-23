"""A self-hosted sandbox worker: the agent's tools run here, in your container.

The agent loop stays on Anthropic's side. This process long-polls Anthropic's work queue
(outbound only; nothing dials in), runs each tool call locally, and posts the result back.

Run it with ``docker compose up`` from this directory (see README.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.lib.environments import EnvironmentWorker
from anthropic.lib.tools import BetaAsyncFunctionTool
from anthropic.lib.tools.agent_toolset import AgentToolContext, beta_agent_toolset_20260401
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

WORKDIR = os.environ.get("CONCIERGE_WORKDIR", "/workspace")

log = logging.getLogger("concierge.worker")

# The input field that says what each built-in tool acted on.
_TOOL_TARGET = {
    "read": "file_path",
    "write": "file_path",
    "edit": "file_path",
    "glob": "pattern",
    "grep": "pattern",
    "bash": "command",
}


def logged_toolset(ctx: AgentToolContext) -> list[BetaAsyncFunctionTool[Any]]:
    """The SDK's built-in tools, each logging what it ran on before it runs.

    The SDK logs only ``executing tool tool=read tool_use_id=...``. This line adds the
    file, pattern or command, so the worker's output shows the agent's work happening here.
    """
    tools = beta_agent_toolset_20260401(ctx)
    for tool in tools:
        tool.call = _log_call(tool.name, tool.call)
    return tools


def _log_call(
    name: str, call: Callable[[object], Awaitable[object]]
) -> Callable[[object], Awaitable[object]]:
    field = _TOOL_TARGET.get(name, "")

    async def logged(tool_input: object) -> object:
        target = tool_input.get(field, "") if isinstance(tool_input, dict) else ""
        log.info("tool ran in this container: %s %s", name, str(target)[:120])
        return await call(tool_input)

    return logged


class _ClearerSdkToolLines(logging.Filter):
    """Reword two of the SDK runner's tool lines for this demo's readers.

    ``executing tool`` is dropped: ``logged_toolset`` prints a fuller line. ``not owned by
    this runner`` reads like a warning, but for a custom tool it is the expected outcome:
    the client that created the session (``issue_perks.py``) runs it, not this container.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if str(record.msg).startswith("executing tool "):
            return False
        if "not owned by this runner" in str(record.msg) and len(record.args or ()) == 2:
            name, tool_use_id = record.args  # type: ignore[misc]
            record.msg = "custom tool %s runs in your client, not here (tool_use_id=%s)"
            record.args = (name, tool_use_id)
        return True


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
    # The SDK worker logs polling and each claimed work item at INFO; without this the
    # container prints nothing until something fails.
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpx2"):  # one line per long poll otherwise
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("anthropic.lib.tools._beta_session_runner").addFilter(_ClearerSdkToolLines())
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
            tools=logged_toolset,
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
