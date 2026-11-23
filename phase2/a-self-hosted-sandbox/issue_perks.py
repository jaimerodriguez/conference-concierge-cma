"""Issue sponsor perk codes with the secret kept on the host, not in a vault.

Phase 1 stores the CloudCredits API key as a vault ``environment_variable`` credential that
Anthropic substitutes at egress. A self-hosted sandbox has its own egress, so there is
nowhere to substitute it. The replacement: a **custom tool** (see ``concierge/perks.py``).
The agent asks for the tool, this process (which holds the key) makes the call, and only
the result goes back.

    uv run python phase2/a-self-hosted-sandbox/issue_perks.py
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown

from concierge.clients import get_client
from concierge.config import get_settings
from concierge.managed import ManagedResources
from concierge.perks import run_custom_tool
from concierge.progress import Progress
from concierge.sessions import budget, console_url, follow_session, user_message
from concierge.telemetry import setup_telemetry, shutdown_telemetry

AGENT = "Speaker Liaison"
console = Console()


def run_and_show(name: str, tool_input: dict[str, Any]) -> str:
    """Run the custom tool here, and say so: not in the worker container, not at Anthropic."""
    member = tool_input.get("member_id", "a speaker")
    console.print(
        f"[dim]\\[{AGENT}][/dim] issuing a perk code for {member} "
        "[dim](runs in this script, not the worker)[/dim]"
    )
    return run_custom_tool(name, tool_input)


def main() -> None:
    setup_telemetry("concierge-cli")
    settings = get_settings()
    managed = ManagedResources(settings.managed_dir)
    client = get_client()
    session = client.beta.sessions.create(
        agent=managed.agent_id("speaker-liaison-host-tool"),
        environment_id=managed.environment_id(),
        title="Issue speaker perks (host-side tool)",
        vault_ids=[managed.vault_id()],  # still used for the Event DB's bearer token
        budget=budget(settings.helper_budget_cents),
    )
    result = follow_session(
        client,
        session.id,
        send=[user_message("Issue perk codes for every accepted speaker.")],
        custom_tools=run_and_show,
        on_text=lambda text: console.print(Markdown(text)),
        on_event=Progress(console, lead=AGENT),
    )
    console.print(f"\n[dim]Session:[/dim] {console_url(result.session_id)}")
    if not result.ok:
        console.print(f"[yellow]Stopped: {result.stop_reason}[/yellow]")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
