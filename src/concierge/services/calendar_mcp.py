"""The Calendar MCP server: the organizer's calendar.

Every request must carry an OAuth access token issued by ``oauth.py`` (see ``app.py``).
The token says *who* is acting, so bookings are recorded as made by the organizer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer

from concierge.services.auth import current_subject, log_oauth, logger
from concierge.services.store import Store


def _parse(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"Use ISO 8601 local time such as 2026-12-10T18:30, got {value!r}"
        ) from error


def _log_call(tool: str, detail: str = "") -> str:
    """Log one tool call and the credential it came with. Never logs the token itself."""
    subject = current_subject.get("unknown")
    if "static token" in subject:  # phase 2b only: no OAuth involved
        logger.info("Calendar MCP: %s call authorized by a static token%s", tool, detail)
    else:
        # Guide 07 (Step 6, server side): this line shows the vaulted OAuth token reached us.
        log_oauth(
            "MCP CALL",
            f"Calendar MCP {tool} authorized by the OAuth access token for {subject}{detail}",
        )
    return subject


def build_calendar_server(store: Store) -> MCPServer:
    server = MCPServer(
        name="calendar",
        instructions="The organizer's calendar. Times are local, ISO 8601 (2026-12-10T18:30).",
    )

    @server.tool()
    def list_events(date: str | None = None) -> list[dict[str, Any]]:
        """List booked events, optionally for one date (YYYY-MM-DD)."""
        _log_call("list_events")
        return store.list_calendar_events(date=date)

    @server.tool()
    def find_free_slots(
        room: str, date: str, window_start: str, window_end: str, minutes: int
    ) -> list[dict[str, str]]:
        """Find free slots of a given length in a room. `window_start` and `window_end` are
        local times (HH:MM) on `date` (YYYY-MM-DD)."""
        _log_call("find_free_slots")
        cursor = _parse(f"{date}T{window_start}")
        end = _parse(f"{date}T{window_end}")
        booked = [
            (_parse(event["starts_at"]), _parse(event["ends_at"]))
            for event in store.list_calendar_events(date=date)
            if event["room"] == room
        ]
        length = timedelta(minutes=minutes)
        slots: list[dict[str, str]] = []
        while cursor + length <= end:
            clash = next((b for b in booked if cursor < b[1] and b[0] < cursor + length), None)
            if clash is None:
                slots.append(
                    {
                        "starts_at": cursor.isoformat(timespec="minutes"),
                        "ends_at": (cursor + length).isoformat(timespec="minutes"),
                    }
                )
                cursor += length
            else:
                cursor = clash[1]
        return slots

    @server.tool()
    def create_event(title: str, room: str, starts_at: str, ends_at: str) -> dict[str, Any]:
        """Book a slot on the organizer's calendar. Fails if the room is already booked."""
        subject = _log_call("create_event", f": booking {title!r} in {room} at {starts_at}")
        return store.add_calendar_event(
            title=title,
            room=room,
            starts_at=_parse(starts_at).isoformat(timespec="minutes"),
            ends_at=_parse(ends_at).isoformat(timespec="minutes"),
            # Set by the bearer middleware from the OAuth token: the booking is the organizer's.
            created_by=subject,
        )

    return server
