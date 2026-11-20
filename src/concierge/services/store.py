"""SQLite storage for the mock services. Standard library only."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id TEXT PRIMARY KEY,
    contact_email TEXT NOT NULL,
    persona TEXT,
    roles TEXT NOT NULL DEFAULT '["attendee"]',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members(id),
    event_id TEXT NOT NULL,
    track TEXT NOT NULL,
    format TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'submitted',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    proposal_id TEXT PRIMARY KEY REFERENCES proposals(id),
    scores TEXT NOT NULL,
    overall REAL NOT NULL,
    recommendation TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    room TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS perks (
    member_id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    amount_usd INTEGER NOT NULL,
    recorded INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    scope TEXT NOT NULL,
    subject TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    token TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    client_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    subject TEXT NOT NULL,
    expires_at REAL
);
"""

# Tables that runs fill: `concierge data clear` empties these. Children before parents.
# The oauth_* tables are left alone: they hold the Calendar sign-in your vault depends on.
DEMO_TABLES = ("reviews", "perks", "calendar_events", "proposals", "members")

PROPOSAL_STATUSES = ("submitted", "reviewed", "accepted", "waitlisted", "declined")
RECOMMENDATIONS = ("accept", "waitlist", "decline")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


class Store:
    """A small data-access layer. Each call opens its own short-lived connection."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)
            _migrate_member_name_to_contact_email(db)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:  # commit on success, roll back on error
                yield db
        finally:
            db.close()

    def _all(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def _one(self, sql: str, *params: Any) -> dict[str, Any] | None:
        rows = self._all(sql, *params)
        return rows[0] if rows else None

    # --- members -------------------------------------------------------------------

    def add_member(self, contact_email: str, persona: str | None = None) -> dict[str, Any]:
        member_id = new_id("mem")
        with self._connect() as db:
            db.execute(
                "INSERT INTO members (id, contact_email, persona, created_at) VALUES (?, ?, ?, ?)",
                (member_id, contact_email, persona, time.time()),
            )
        return self.get_member(member_id)  # type: ignore[return-value]

    def find_or_add_member(self, contact_email: str, persona: str | None = None) -> dict[str, Any]:
        """The member with this contact email (ignoring case), or a new one.

        One person submitting twice is one member with two proposals, not two members with
        the same email. The first persona stays; it only shapes how an abstract is written.
        """
        contact_email = contact_email.strip()
        row = self._one(
            "SELECT * FROM members WHERE lower(contact_email) = lower(?)"
            " ORDER BY created_at LIMIT 1",
            contact_email,
        )
        return _decode_member(row) if row else self.add_member(contact_email, persona=persona)

    def get_member(self, member_id: str) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM members WHERE id = ?", member_id)
        return _decode_member(row) if row else None

    def list_members(self, role: str | None = None) -> list[dict[str, Any]]:
        members = [
            _decode_member(row) for row in self._all("SELECT * FROM members ORDER BY contact_email")
        ]
        return [m for m in members if role is None or role in m["roles"]]

    def add_role(self, member_id: str, role: str) -> None:
        """One member profile, many roles: an attendee becomes a speaker by gaining a role."""
        member = self.get_member(member_id)
        if member is None:
            raise KeyError(f"Unknown member {member_id}")
        if role not in member["roles"]:
            roles = json.dumps([*member["roles"], role])
            with self._connect() as db:
                db.execute("UPDATE members SET roles = ? WHERE id = ?", (roles, member_id))

    # --- proposals -----------------------------------------------------------------

    def add_proposal(
        self,
        *,
        member_id: str,
        event_id: str,
        track: str,
        format: str,
        title: str,
        abstract: str,
        source: str,
    ) -> dict[str, Any]:
        proposal_id = new_id("prop")
        with self._connect() as db:
            db.execute(
                "INSERT INTO proposals (id, member_id, event_id, track, format, title, abstract,"
                " source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal_id,
                    member_id,
                    event_id,
                    track,
                    format,
                    title,
                    abstract,
                    source,
                    time.time(),
                ),
            )
        self.add_role(member_id, "submitter")
        return self.get_proposal(proposal_id)  # type: ignore[return-value]

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        row = self._one(
            "SELECT p.*, m.contact_email FROM proposals p"
            " JOIN members m ON m.id = p.member_id WHERE p.id = ?",
            proposal_id,
        )
        if row is None:
            return None
        row["review"] = self.get_review(proposal_id)
        return row

    def list_proposals(
        self, status: str | None = None, track: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT p.id, p.title, p.track, p.format, p.status, p.member_id,"
            " m.contact_email, r.overall, r.recommendation"
            " FROM proposals p JOIN members m ON m.id = p.member_id"
            " LEFT JOIN reviews r ON r.proposal_id = p.id ORDER BY p.created_at"
        )
        return [
            row
            for row in rows
            if (status is None or row["status"] == status)
            and (track is None or row["track"] == track)
        ]

    def list_board_proposals(self) -> list[dict[str, Any]]:
        """Every proposal with what the public board shows: abstract, score, and feedback.

        Kept apart from ``list_proposals`` so the Event DB tool stays short for agents.
        """
        return self._all(
            "SELECT p.id, p.title, p.abstract, p.track, p.format, p.status, p.source,"
            " p.created_at, m.contact_email, r.overall, r.recommendation, r.summary"
            " FROM proposals p JOIN members m ON m.id = p.member_id"
            " LEFT JOIN reviews r ON r.proposal_id = p.id"
            " ORDER BY r.overall IS NULL, r.overall DESC, p.created_at DESC"
        )

    def set_proposal_status(self, proposal_id: str, status: str) -> dict[str, Any]:
        if status not in PROPOSAL_STATUSES:
            raise ValueError(f"status must be one of {PROPOSAL_STATUSES}")
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            raise KeyError(f"Unknown proposal {proposal_id}")
        with self._connect() as db:
            db.execute("UPDATE proposals SET status = ? WHERE id = ?", (status, proposal_id))
        if status == "accepted":
            self.add_role(proposal["member_id"], "speaker")
        return self.get_proposal(proposal_id)  # type: ignore[return-value]

    def record_review(
        self,
        proposal_id: str,
        *,
        scores: dict[str, int],
        overall: float,
        recommendation: str,
        summary: str,
    ) -> dict[str, Any]:
        if recommendation not in RECOMMENDATIONS:
            raise ValueError(f"recommendation must be one of {RECOMMENDATIONS}")
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            raise KeyError(f"Unknown proposal {proposal_id}")
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO reviews (proposal_id, scores, overall, recommendation,"
                " summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (proposal_id, json.dumps(scores), overall, recommendation, summary, time.time()),
            )
            # A review never accepts or declines: only the organizer does that.
            if proposal["status"] == "submitted":
                db.execute("UPDATE proposals SET status = 'reviewed' WHERE id = ?", (proposal_id,))
        return self.get_proposal(proposal_id)  # type: ignore[return-value]

    def get_review(self, proposal_id: str) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM reviews WHERE proposal_id = ?", proposal_id)
        if row is None:
            return None
        row["scores"] = json.loads(row["scores"])
        return row

    # --- calendar ------------------------------------------------------------------

    def list_calendar_events(self, date: str | None = None) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM calendar_events ORDER BY starts_at")
        return [row for row in rows if date is None or row["starts_at"].startswith(date)]

    def add_calendar_event(
        self, *, title: str, room: str, starts_at: str, ends_at: str, created_by: str
    ) -> dict[str, Any]:
        if ends_at <= starts_at:
            raise ValueError("ends_at must be after starts_at")
        for event in self.list_calendar_events():
            overlaps = starts_at < event["ends_at"] and event["starts_at"] < ends_at
            if event["room"] == room and overlaps:
                raise ValueError(
                    f"{room} is already booked {event['starts_at']} to {event['ends_at']} "
                    f"for {event['title']!r}"
                )
        event_id = new_id("cal")
        with self._connect() as db:
            db.execute(
                "INSERT INTO calendar_events (id, title, room, starts_at, ends_at, created_by,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_id, title, room, starts_at, ends_at, created_by, time.time()),
            )
        return self._one("SELECT * FROM calendar_events WHERE id = ?", event_id)  # type: ignore[return-value]

    # --- sponsor perks -------------------------------------------------------------

    def issue_perk(self, member_id: str, amount_usd: int) -> dict[str, Any]:
        """Issue a code, or return the existing one: calling twice is safe (idempotent)."""
        existing = self._one("SELECT * FROM perks WHERE member_id = ?", member_id)
        if existing:
            return existing
        code = f"CLOUD-{secrets.token_hex(3).upper()}-{amount_usd}"
        with self._connect() as db:
            db.execute(
                "INSERT INTO perks (member_id, code, amount_usd, created_at) VALUES (?, ?, ?, ?)",
                (member_id, code, amount_usd, time.time()),
            )
        return self._one("SELECT * FROM perks WHERE member_id = ?", member_id)  # type: ignore[return-value]

    def mark_perk_recorded(self, member_id: str, code: str) -> dict[str, Any]:
        perk = self._one("SELECT * FROM perks WHERE member_id = ?", member_id)
        if perk is None or perk["code"] != code:
            raise ValueError("That code was not issued to this member.")
        with self._connect() as db:
            db.execute("UPDATE perks SET recorded = 1 WHERE member_id = ?", (member_id,))
        return {**perk, "recorded": 1}

    # --- OAuth ---------------------------------------------------------------------

    # --- demo data -----------------------------------------------------------------

    def demo_data_counts(self) -> dict[str, int]:
        """Rows per table that runs create (see DEMO_TABLES)."""
        with self._connect() as db:
            return {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in DEMO_TABLES
            }

    def clear_demo_data(self) -> dict[str, int]:
        """Delete every row in DEMO_TABLES, in one transaction. Returns what was deleted."""
        counts = self.demo_data_counts()
        with self._connect() as db:
            for table in DEMO_TABLES:
                db.execute(f"DELETE FROM {table}")  # fixed table names, not input
        return counts

    def save_oauth_code(self, **fields: Any) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO oauth_codes (code, client_id, redirect_uri, code_challenge, scope,"
                " subject, expires_at) VALUES (:code, :client_id, :redirect_uri,"
                " :code_challenge, :scope, :subject, :expires_at)",
                fields,
            )

    def take_oauth_code(self, code: str) -> dict[str, Any] | None:
        """Return and delete a code: authorization codes are single-use."""
        row = self._one("SELECT * FROM oauth_codes WHERE code = ?", code)
        if row is None:
            return None
        with self._connect() as db:
            db.execute("DELETE FROM oauth_codes WHERE code = ?", (code,))
        return row if row["expires_at"] > time.time() else None

    def save_oauth_token(
        self,
        *,
        token: str,
        kind: str,
        client_id: str,
        scope: str,
        subject: str,
        expires_at: float | None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO oauth_tokens (token, kind, client_id, scope, subject, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (token, kind, client_id, scope, subject, expires_at),
            )

    def get_oauth_token(self, token: str, kind: str) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM oauth_tokens WHERE token = ? AND kind = ?", token, kind)
        if row is None:
            return None
        if row["expires_at"] is not None and row["expires_at"] <= time.time():
            return None
        return row

    def delete_oauth_token(self, token: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM oauth_tokens WHERE token = ?", (token,))


def _migrate_member_name_to_contact_email(db: sqlite3.Connection) -> None:
    """Upgrade a database from before members had a contact email instead of a first name.

    Old demo rows hold first names, so each becomes a placeholder ``name@example.com``
    (example.com is reserved for examples and never delivers mail).
    """
    columns = {row["name"] for row in db.execute("PRAGMA table_info(members)")}
    if "name" not in columns or "contact_email" in columns:
        return
    db.execute("ALTER TABLE members RENAME COLUMN name TO contact_email")
    db.execute(
        "UPDATE members SET contact_email ="
        " lower(replace(trim(contact_email), ' ', '.')) || '@example.com'"
        " WHERE contact_email NOT LIKE '%@%'"
    )


def _decode_member(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "roles": json.loads(row["roles"])}
