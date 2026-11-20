# Guide 05 · Wiring up OpenTelemetry

**You'll learn:** how to see the demo's Claude calls as traces in your own backend.

There are two independent sources of spans. Together they form one trace.

| | SDK tracing | API tracing |
|---|---|---|
| Emitted by | The SDK, in your process | Anthropic, server-side |
| Set up with | Code (this guide) | A destination an organization admin adds |
| Shows | Your requests, session calls, token usage | Each model request, agent turns, server and MCP tool runs |

Start with the Console's session viewer (`concierge` prints a link for every session): it
needs no setup. Add OpenTelemetry when you want traces in your own tools.

## Steps

**Step 1. Set tracing up once, at process start.**
Find it: `src/concierge/cli.py`, marker `Guide 05 · ... · Step 1`.

**Step 2. Register a tracer provider** before the first SDK call.
Find it: `src/concierge/telemetry.py`, marker `Step 2`.

**Step 3. Tell the SDK to use it**, and choose a content mode.
Find it: `src/concierge/telemetry.py`, marker `Step 3`.

**Step 4. Wrap an operation in your own span** so everything it does nests under it.
Find it: `src/concierge/proposals.py`, marker `Step 4`.

**Step 5. Run a backend.** Jaeger accepts OTLP directly.
Find it: `docker-compose.yml`, marker `Step 5`.

**Step 6. Optional: add API tracing.** (No marker: no code.) An organization admin adds a
destination in the Console or through the Admin API. It must be an OTLP/HTTP endpoint at a
public HTTPS address on port 443, so the local Jaeger above cannot receive it; use a hosted
backend or a collector you expose. Adding a destination sends traces of your organization's
activity to that service, so it is a decision for the organization's admin.

## Try it
```sh
docker compose up -d
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
uv run concierge propose "Running models locally"
open http://localhost:16686     # service: concierge-cli
```

## What to notice
- **Content mode.** `metadata_only` (the default) exports IDs, timing, and token counts.
  `CONCIERGE_OTEL_CONTENT_MODE=content` also exports prompts and responses: your backend
  then stores audience input under its own access and retention rules.
- Spans use the OpenTelemetry GenAI conventions (`gen_ai.*`).
- OpenTelemetry export is in beta; span names and attributes can change, so pin the SDK.
- In phase 2a the worker emits the tool spans (Guide 20).
