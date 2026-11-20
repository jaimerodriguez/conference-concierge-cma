# Phase 2a: self-hosted sandbox

Tools run in a container you own; the agent loop stays at Anthropic.
Follow [Guide 20](../../docs/guides/20-self-hosted-sandbox.md).

| File | What it is |
|---|---|
| `worker.py` | The SDK `EnvironmentWorker`, with graceful shutdown and tracing |
| `Dockerfile`, `docker-compose.yml` | The sandbox image and how to run it |
| `issue_perks.py` | The sponsor-perk flow with the secret held host-side (custom tool) |

The environment and the agent variant live with the other managed files:
`managed/environments/self-hosted.yaml` and `managed/agents/speaker-liaison-host-tool/`.
