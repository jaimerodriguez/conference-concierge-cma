"""Routes for the proposal portal.

The portal is the demo's *client application*: it calls Claude (moderation, then an
abstract-writing session) and saves the result. Writing an abstract takes a little while, so
a submission becomes a background job and the page polls for the result.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import BaseRoute, Route
from starlette.templating import Jinja2Templates

from concierge.catalog import Catalog
from concierge.clients import get_client
from concierge.config import Settings
from concierge.moderation import MAX_ABSTRACT_CHARS, MAX_TITLE_CHARS, MAX_TOPIC_CHARS
from concierge.proposals import MAX_EMAIL_CHARS, ProposalOutcome, normalize_email, submit_proposal
from concierge.services.store import Store

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")


def mask_email(address: str) -> str:
    """Hide most of an address for the public board.

    "ada.lovelace@example.com" becomes "ad***e@example.com".

    The first two letters and the last letter of the part before the @ stay; the mask is a fixed
    width so it does not give away the length. Prefixes of three letters or fewer keep only
    their first letter, so nothing short is shown in full.
    """
    local, at, domain = address.rpartition("@")
    if not at:
        return "***"
    shown = f"{local[:2]}***{local[-1]}" if len(local) > 3 else f"{local[:1]}***"
    return f"{shown}@{domain}"


TEMPLATES.env.filters["mask_email"] = mask_email

MIN_ABSTRACT_CHARS = 50
RATE_LIMIT_SUBMISSIONS = 3  # per client address...
RATE_LIMIT_WINDOW_SECONDS = 10 * 60  # ...per ten minutes
MAX_CONCURRENT_JOBS = 8

LIMITS = {
    "email": MAX_EMAIL_CHARS,
    "topic": MAX_TOPIC_CHARS,
    "title": MAX_TITLE_CHARS,
    "abstract": MAX_ABSTRACT_CHARS,
    "abstract_min": MIN_ABSTRACT_CHARS,
}


@dataclass(frozen=True)
class BoardGroup:
    """One section of the proposal board and the statuses it collects."""

    key: str
    label: str
    statuses: frozenset[str]
    blurb: str


# Waitlisted proposals were reviewed and are still in the running, so they sit with "Reviewed".
# Proposals not reviewed yet get their own section, so a fresh submission is always visible.
BOARD_GROUPS = (
    BoardGroup("accepted", "Accepted", frozenset({"accepted"}), "On the agenda."),
    BoardGroup(
        "reviewed",
        "Reviewed",
        frozenset({"reviewed", "waitlisted"}),
        "Scored by the CFP Reviewer, waiting for the organizers' decision.",
    ),
    BoardGroup("declined", "Not this time", frozenset({"declined"}), "Thank you for proposing!"),
    BoardGroup(
        "submitted",
        "Awaiting review",
        frozenset({"submitted"}),
        "The Program Chair reviews new proposals every morning.",
    ),
)

NEXT_STEPS = {
    "accepted": "You're on the agenda. Watch for your time slot and the sponsor perk code.",
    "reviewed": "Reviewed. The organizers decide soon.",
    "waitlisted": "On the waitlist. We'll reach out if a slot opens up.",
    "declined": "Not this time. We'd love a new proposal for the next meetup.",
    "submitted": "Waiting for the morning review.",
}


@dataclass
class Job:
    topic: str
    writes_abstract: bool = True
    outcome: ProposalOutcome | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)


def build_routes(settings: Settings, store: Store, catalog: Catalog) -> list[BaseRoute]:
    jobs: dict[str, Job] = {}
    tasks: set[asyncio.Task[None]] = set()  # keep references so tasks are not collected
    recent: dict[str, deque[float]] = defaultdict(deque)
    slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    def rate_limited(client_address: str) -> bool:
        now = time.time()
        window = recent[client_address]
        while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= RATE_LIMIT_SUBMISSIONS:
            return True
        window.append(now)
        return False

    async def run_job(job: Job, form: dict[str, str]) -> None:
        async with slots:
            try:
                # The SDK client is synchronous, so run the pipeline in a worker thread.
                job.outcome = await asyncio.to_thread(
                    submit_proposal,
                    get_client(),
                    store,
                    contact_email=form["contact_email"],
                    persona_id=form["persona"],
                    track_id=form["track"],
                    topic=form["topic"],
                    title=None if form["ai_abstract"] else form["title"],
                    abstract=None if form["ai_abstract"] else form["abstract"],
                    settings=settings,
                )
            except Exception as error:
                job.error = f"{type(error).__name__}: {error}"

    def form_context(
        error: str | None = None, values: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        # `values` refills the form after an error, so nobody retypes an abstract.
        return {
            "catalog": catalog,
            "error": error,
            "values": values or {"ai_abstract": True},
            "limits": LIMITS,
        }

    def validate(form: dict[str, Any]) -> str | None:
        """The first problem with a submission, in the order the form asks, or None."""
        known_personas = {persona.id for persona in catalog.personas}
        known_tracks = {track.id for track in catalog.tracks}
        if normalize_email(form["contact_email"]) is None:
            return "Please enter a valid contact email, like sam@example.com."
        if form["persona"] not in known_personas or form["track"] not in known_tracks:
            return "Pick a persona and a track."
        if form["ai_abstract"]:
            if not form["topic"]:
                return "Pick or type a topic."
            if len(form["topic"]) > MAX_TOPIC_CHARS:
                return f"Please keep the topic under {MAX_TOPIC_CHARS} characters."
            return None
        if not form["title"]:
            return "Give your talk a title."
        if len(form["title"]) > MAX_TITLE_CHARS:
            return f"Please keep the title under {MAX_TITLE_CHARS} characters."
        if len(form["abstract"]) < MIN_ABSTRACT_CHARS:
            return f"Please write an abstract of at least {MIN_ABSTRACT_CHARS} characters."
        if len(form["abstract"]) > MAX_ABSTRACT_CHARS:
            return f"Please keep the abstract under {MAX_ABSTRACT_CHARS} characters."
        return None

    async def index(request: Request) -> Response:
        return TEMPLATES.TemplateResponse(request, "form.html", form_context())

    async def propose(request: Request) -> Response:
        data = await request.form()

        def text(key: str) -> str:
            return str(data.get(key, "")).strip()

        form: dict[str, Any] = {
            "contact_email": text("contact_email"),
            "persona": text("persona"),
            "track": text("track"),
            "topic": text("custom_topic") or text("topic"),
            "picked_topic": text("topic"),
            "custom_topic": text("custom_topic"),
            # An unchecked checkbox is simply missing from the form data.
            "ai_abstract": "ai_abstract" in data,
            "title": text("title"),
            "abstract": text("abstract"),
        }
        if problem := validate(form):
            return TEMPLATES.TemplateResponse(
                request, "form.html", form_context(problem, form), status_code=400
            )
        # Behind a tunnel every request comes from the proxy, so prefer the forwarded
        # address. This header can be forged; it is good enough for a demo, not for production.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        client_address = forwarded or (request.client.host if request.client else "unknown")
        if rate_limited(client_address):
            return TEMPLATES.TemplateResponse(
                request,
                "form.html",
                form_context("That's a lot of talks! Give others a turn and try again soon.", form),
                status_code=429,
            )

        job_id = secrets.token_urlsafe(8)
        jobs[job_id] = Job(
            topic=form["topic"] if form["ai_abstract"] else form["title"],
            writes_abstract=form["ai_abstract"],
        )
        task = asyncio.create_task(run_job(jobs[job_id], form))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return RedirectResponse(request.url_for("status", job_id=job_id), status_code=303)

    async def status(request: Request) -> Response:
        job = jobs.get(request.path_params["job_id"])
        if job is None:
            return RedirectResponse(request.url_for("index"), status_code=303)
        return TEMPLATES.TemplateResponse(
            request, "status.html", {"job": job, "catalog": catalog, "now": time.time()}
        )

    async def board(request: Request) -> Response:
        proposals = await asyncio.to_thread(store.list_board_proposals)
        track_names = {track.id: track.name for track in catalog.tracks}
        track = request.query_params.get("track")
        if track not in track_names:
            track = None
        shown = [p for p in proposals if track is None or p["track"] == track]
        groups = [
            (group, [p for p in shown if p["status"] in group.statuses]) for group in BOARD_GROUPS
        ]
        return TEMPLATES.TemplateResponse(
            request,
            "board.html",
            {
                "catalog": catalog,
                "groups": groups,
                "total": len(shown),
                "track_names": track_names,
                "track_counts": {t: sum(p["track"] == t for p in proposals) for t in track_names},
                "all_count": len(proposals),
                "selected_track": track,
                "next_steps": NEXT_STEPS,
            },
        )

    return [
        Route("/", index, name="index"),
        Route("/propose", propose, methods=["POST"], name="propose"),
        Route("/status/{job_id}", status, name="status"),
        Route("/board", board, name="board"),
    ]
