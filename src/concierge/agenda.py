"""How much talk time the evening has, and whether a set of proposals fits in it.

Agents are poor at adding up minutes, and the Program Chair once accepted four proposals on top
of eight already accepted: 160 minutes of talks in a 150-minute window. The arithmetic lives
here instead, behind the Event DB ``check_agenda_fit`` tool, so the chair (before accepting) and
the Scheduler (before booking) read the same numbers.
"""

from __future__ import annotations

from typing import Any

from concierge.catalog import Event


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def talk_budget(event: Event) -> dict[str, int]:
    """The evening's minutes: the window, what breaks and the buffer take, and what is left.

    One break for each full hour after the first (a 150-minute evening has two), and one
    buffer before the end, because talks run over.
    """
    window = _minutes(event.talks_end) - _minutes(event.talks_start)
    breaks = max(0, (window - 1) // 60)
    break_minutes = breaks * event.slots.break_minutes
    return {
        "window_minutes": window,
        "breaks": breaks,
        "break_minutes": break_minutes,
        "buffer_minutes": event.slots.buffer_minutes,
        "talk_minutes_available": window - break_minutes - event.slots.buffer_minutes,
    }


def slot_minutes(event: Event, proposal_format: str) -> int:
    if proposal_format == "lightning":
        return event.slots.lightning_minutes
    return event.slots.talk_minutes


def check_fit(
    event: Event,
    accepted: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Whether ``candidates`` fit on top of the ``accepted`` proposals.

    Candidates are taken in the order given; one that does not fit is skipped and the next is
    tried, so a short lightning talk can still fit after a long talk did not.
    """
    budget = talk_budget(event)
    used = sum(slot_minutes(event, p["format"]) for p in accepted)
    accepted_ids = {p["id"] for p in accepted}
    remaining = budget["talk_minutes_available"] - used
    fits: list[dict[str, Any]] = []
    does_not_fit: list[dict[str, Any]] = []
    for proposal in candidates:
        if proposal["id"] in accepted_ids:
            continue  # already counted
        minutes = slot_minutes(event, proposal["format"])
        entry = {"id": proposal["id"], "title": proposal["title"], "minutes": minutes}
        if minutes <= remaining:
            remaining -= minutes
            fits.append(entry)
        else:
            does_not_fit.append(entry)
    return {
        **budget,
        "accepted_count": len(accepted),
        "accepted_minutes": used,
        # Negative when the proposals already accepted overrun the evening.
        "minutes_left_after_fits": remaining,
        "already_overrun": used > budget["talk_minutes_available"],
        "fits": fits,
        "does_not_fit": does_not_fit,
    }
