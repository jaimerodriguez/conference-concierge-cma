# Guide 05 · Wiring up OpenTelemetry

**You'll learn:** how to see the demo's Claude calls as traces in your own backend.

## New to tracing? The three words you need

- **OpenTelemetry (OTel)** is an open standard for describing what a program did as
  *traces*. A trace is one operation (say, submitting a proposal) broken into *spans*: timed
  steps like "moderate the title" or "call the model", nested inside each other. Code that
  speaks OTel can send its spans to any tool that understands the standard.
- **OTLP** is the wire format OTel uses to send spans. This demo sends it over plain HTTP.
- **Jaeger** is a free, open source tool that receives traces and shows them in a web page
  as a timeline. It is the *backend* in this guide: it runs on your machine in Docker, keeps
  traces in memory (they are gone when the container stops), and needs no account.

There are two independent sources of spans. Together they form one trace.

| | SDK tracing | API tracing |
|---|---|---|
| Emitted by | The SDK, in your process | Anthropic, server-side |
| Set up with | Code (this guide) | A destination an organization admin adds |
| Shows | Your requests, session calls, token usage | Each model request, agent turns, server and MCP tool runs |

Start with the Console's session viewer (`concierge` prints a link for every session): it
needs no setup. Add OpenTelemetry when you want traces in your own tools.

## Settings

| Setting | Where | What it does |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `.env` or your shell | Where spans go. `http://localhost:4318` is the local Jaeger. **Unset means tracing is off**: nothing is recorded or sent. This is a standard OTel variable, so the exporter also honors the other standard ones, such as `OTEL_EXPORTER_OTLP_HEADERS` for a backend that needs an API key. |
| `CONCIERGE_OTEL_CONTENT_MODE` | `.env` | `metadata_only` (default) or `content`. See *What to notice*. |
| Service name | Code, not a setting | How a process appears in Jaeger: `concierge-cli` for terminal commands, `concierge-portal` for `concierge services`. |

| Port | Who listens | Used for |
|---|---|---|
| `16686` | Jaeger | The Jaeger web page you open in a browser. |
| `4318` | Jaeger | OTLP over HTTP: the demo's processes send spans here. Jaeger accepts OTLP directly, so no separate collector is needed. |

## Steps

**Step 1. Set tracing up once, at process start.**
Find it: `src/concierge/cli.py`, marker `Guide 05 · ... · Step 1`.

**Step 2. Register a tracer provider** before the first SDK call.
The provider is the object that collects spans in your process and hands them to an
exporter, which sends them to `OTEL_EXPORTER_OTLP_ENDPOINT`.
Find it: `src/concierge/telemetry.py`, marker `Step 2`.

**Step 3. Tell the SDK to use it**, and choose a content mode.
Find it: `src/concierge/telemetry.py`, marker `Step 3`.

**Step 4. Wrap an operation in your own span** so everything it does nests under it.
Find it: `src/concierge/proposals.py`, marker `Step 4`.

**Step 5. Run a backend.** Jaeger accepts OTLP directly.
Find it: `docker-compose.yml`, marker `Step 5`.

**Step 6. Optional: add API tracing.** (No marker: no code.)
Steps 1 to 5 trace what happens *in your process*. Once a request reaches Anthropic, your
process only sees how long the call took. For a Managed Agents session that is most of the
story: the agent's turns, each model request, and the server and MCP tool runs all happen on
Anthropic's side. API tracing has Anthropic send spans for that work to a backend you name.

| | Local setup only (Steps 1 to 5) | Local setup plus API tracing |
|---|---|---|
| Who sends spans | Your process | Your process and Anthropic |
| Where they go | Jaeger on your machine | A backend with a public HTTPS address |
| What a trace shows | Your span, moderation, the SDK calls, their timing and tokens | All of that, plus agent turns, model requests, and tool runs nested inside the SDK calls |
| Who sets it up | You, in code | An organization admin, once, for the whole organization |

How it is added: an admin opens the organization's OpenTelemetry settings in the Console
([platform.claude.com/settings/telemetry-destinations](https://platform.claude.com/settings/telemetry-destinations),
then *Add destination*) or calls the Admin API. They
give an OTLP/HTTP endpoint and any headers it needs (for example an API key), pick a content
mode, and choose which workspaces it covers. *Test* sends an `anthropic.test` span to check
the connection.

Why the local Jaeger cannot be the destination: Anthropic's servers send the spans over the
internet, so the endpoint must be HTTPS on port 443, at a hostname that resolves to a public
address. `localhost:4318` is neither. Use a hosted observability service, or put your own
collector behind a public HTTPS address.

How the two halves join into one trace: the SDK sends a standard `traceparent` header with
each request, and Anthropic attaches its spans to it. This only shows up as one trace when
both sources send to the same backend, so with API tracing on, point
`OTEL_EXPORTER_OTLP_ENDPOINT` at that same service.

Decide before you turn it on: a destination receives traces of the activity in every
workspace it covers, and with content mode `content` it also receives prompts and responses.
It is an organization decision, which is why only admins can add one. API tracing is in beta.
Reference: [OpenTelemetry for the Claude API](https://platform.claude.com/docs/en/manage-claude/opentelemetry).

## Try it
```sh
# From the root of the repository, where docker-compose.yml is
docker compose up -d                              # starts Jaeger
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
uv run concierge propose "Running models locally"  # the argument is the talk's title
open http://localhost:16686                       # pick service concierge-cli, then Find Traces
```
Open the `concierge.submit_proposal` trace. You see your own span with moderation and the
agent session nested inside it, each with its timing and token counts. `docker compose down`
stops Jaeger and discards the traces.

## What to notice
- **Content mode.** `metadata_only` (the default) exports IDs, timing, and token counts.
  `CONCIERGE_OTEL_CONTENT_MODE=content` also exports prompts and responses: your backend
  then stores audience input under its own access and retention rules.
- Spans use the OpenTelemetry GenAI conventions (`gen_ai.*`).
- OpenTelemetry export is in beta; span names and attributes can change, so pin the SDK.
- In phase 2a the worker emits the tool spans (Guide 20).
