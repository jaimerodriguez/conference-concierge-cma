"""The Event DB MCP server: members, proposals, reviews, and perks.

Authentication is a static bearer token (see ``app.py``), stored in the vault as a
``static_bearer`` credential.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from concierge.agenda import check_fit
from concierge.catalog import Catalog
from concierge.services.store import Store


def build_eventdb_server(store: Store, catalog: Catalog) -> MCPServer:
    server = MCPServer(
        name="eventdb",
        instructions="Members, talk proposals, reviews, and sponsor perks for the meetup.",
    )

    @server.tool()
    def get_event() -> dict[str, Any]:
        """Get the current event: name, date, times, slot lengths, venue, and tracks."""
        return {
            **catalog.event.model_dump(),
            "tracks": [track.model_dump() for track in catalog.tracks],
        }

    @server.tool()
    def list_proposals(
        status: Literal["submitted", "reviewed", "accepted", "waitlisted", "declined"]
        | None = None,
        track: str | None = None,
    ) -> list[dict[str, Any]]:
        """List proposals (id, title, track, status, speaker, score), optionally filtered."""
        return store.list_proposals(status=status, track=track)

    @server.tool()
    def check_agenda_fit(add_proposal_ids: list[str] | None = None) -> dict[str, Any]:
        """Check whether proposals fit in the evening before accepting or booking them.

        Counts every proposal already accepted (booked or not) against the talk time left
        after breaks and the end buffer. Pass the proposals you want to add, in the order you
        would pick them; each is listed under 'fits' or 'does_not_fit'. With no ids, it checks
        only what is already accepted."""
        accepted = store.list_proposals(status="accepted")
        candidates = []
        for proposal_id in add_proposal_ids or []:
            proposal = store.get_proposal(proposal_id)
            if proposal is None:
                raise ValueError(f"Unknown proposal {proposal_id}")
            candidates.append(proposal)
        return check_fit(catalog.event, accepted, candidates)

    @server.tool()
    def get_proposal(proposal_id: str) -> dict[str, Any]:
        """Get one proposal in full, including its abstract and its review if it has one."""
        proposal = store.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"Unknown proposal {proposal_id}")
        return proposal

    @server.tool()
    def record_review(
        proposal_id: str,
        scores: dict[str, int],
        overall: float,
        recommendation: Literal["accept", "waitlist", "decline"],
        summary: str,
    ) -> dict[str, Any]:
        """Record a review: per-criterion scores (1-5), the overall score, a recommendation,
        and a two-sentence summary. Moves a submitted proposal to 'reviewed'. It never accepts
        or declines a proposal; only the organizer does that."""
        bad = {name: score for name, score in scores.items() if not 1 <= score <= 5}
        if bad:
            raise ValueError(f"Scores must be between 1 and 5: {bad}")
        return store.record_review(
            proposal_id,
            scores=scores,
            overall=overall,
            recommendation=recommendation,
            summary=summary,
        )

    @server.tool()
    def set_proposal_status(
        proposal_id: str, status: Literal["accepted", "waitlisted", "declined"]
    ) -> dict[str, Any]:
        """Set the organizer's decision on a proposal. Accepting makes its member a speaker."""
        return store.set_proposal_status(proposal_id, status)

    @server.tool()
    def list_members(
        role: Literal["attendee", "submitter", "speaker"] | None = None,
    ) -> list[dict[str, Any]]:
        """List members, optionally only those holding a role."""
        return store.list_members(role=role)

    @server.tool()
    def record_perk(member_id: str, code: str) -> dict[str, Any]:
        """Record that a sponsor perk code was passed on to a speaker."""
        return store.mark_perk_recorded(member_id, code)

    return server
