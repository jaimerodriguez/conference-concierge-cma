"""Issue sponsor perk codes from OUR process, for setups where no vault can inject the key.

Phase 1 keeps the CloudCredits API key in a vault as an ``environment_variable`` credential
that Anthropic substitutes at egress. Outside the cloud sandbox (phases 2a and 2b) there is
nowhere to substitute it, so the call becomes a **custom tool**: the agent asks for the
tool, this process (which holds the key) makes the request, and only the result goes back.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from concierge.config import get_settings

PERK_TOOL_NAME = "issue_perk_code"


def run_custom_tool(name: str, tool_input: dict[str, Any]) -> str:
    """Guide 20 · Moving tools into your own sandbox · Step 4: execute the tool host-side

    The key is read here, from this process's settings. It never enters the session: not
    the prompt, not the sandbox, not the event history.
    """
    if name != PERK_TOOL_NAME:
        raise ValueError(f"Unknown tool {name}")
    settings = get_settings()
    response = httpx.post(
        f"{settings.credits_api_url}/codes",
        headers={"X-Api-Key": settings.cloudcredits_api_key},
        json={"member_id": str(tool_input["member_id"]), "amount_usd": 50},
        timeout=30,
    )
    # Return the API's answer, success or error, so the agent can react to either.
    return json.dumps(response.json())
