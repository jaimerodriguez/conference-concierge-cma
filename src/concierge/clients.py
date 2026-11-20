"""Construct the Claude client used everywhere in the demo."""

from __future__ import annotations

from functools import lru_cache

from anthropic import Anthropic

from concierge.config import get_settings
from concierge.telemetry import sdk_telemetry_option


@lru_cache
def get_client() -> Anthropic:
    """Return a shared client.

    Credentials come from the environment (``ANTHROPIC_API_KEY``) or an ``ant auth login``
    profile. For phase 2b, ``ANTHROPIC_BASE_URL`` points the very same client at your own
    server (see docs/guides/21-migrating-to-self-hosted-managed-agents.md).
    """
    telemetry = sdk_telemetry_option(get_settings().otel_content_mode)
    if telemetry is None:
        return Anthropic()
    return Anthropic(open_telemetry=telemetry)
