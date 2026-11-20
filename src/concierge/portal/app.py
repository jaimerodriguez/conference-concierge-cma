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
from concierge.proposals import ProposalOutcome, submit_proposal
from concierge.services.store import Store

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")

MAX_NAME_CHARS = 40
RATE_LIMIT_SUBMISSIONS = 3  # per client address...
RATE_LIMIT_WINDOW_SECONDS = 10 * 60  # ...per ten minutes
MAX_CONCURRENT_JOBS = 8


@dataclass
class Job:
    topic: str
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
                    member_name=form["name"],
                    persona_id=form["persona"],
                    track_id=form["track"],
                    topic=form["topic"],
                    settings=settings,
                )
            except Exception as error:
                job.error = f"{type(error).__name__}: {error}"

    def form_context(error: str | None = None) -> dict[str, Any]:
        return {"catalog": catalog, "error": error}

    async def index(request: Request) -> Response:
        return TEMPLATES.TemplateResponse(request, "form.html", form_context())

    async def propose(request: Request) -> Response:
        data = await request.form()
        custom_topic = str(data.get("custom_topic", "")).strip()
        form = {
            "name": str(data.get("name", "")).strip()[:MAX_NAME_CHARS],
            "persona": str(data.get("persona", "")),
            "track": str(data.get("track", "")),
            "topic": custom_topic or str(data.get("topic", "")),
        }
        known_personas = {persona.id for persona in catalog.personas}
        known_tracks = {track.id for track in catalog.tracks}
        if form["persona"] not in known_personas or form["track"] not in known_tracks:
            return TEMPLATES.TemplateResponse(
                request, "form.html", form_context("Pick a persona and a track."), status_code=400
            )
        if not form["topic"]:
            return TEMPLATES.TemplateResponse(
                request, "form.html", form_context("Pick or type a topic."), status_code=400
            )
        # Behind a tunnel every request comes from the proxy, so prefer the forwarded
        # address. This header can be forged; it is good enough for a demo, not for production.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        client_address = forwarded or (request.client.host if request.client else "unknown")
        if rate_limited(client_address):
            return TEMPLATES.TemplateResponse(
                request,
                "form.html",
                form_context("That's a lot of talks! Give others a turn and try again soon."),
                status_code=429,
            )

        job_id = secrets.token_urlsafe(8)
        jobs[job_id] = Job(topic=form["topic"])
        task = asyncio.create_task(run_job(jobs[job_id], form))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return RedirectResponse(request.url_for("status", job_id=job_id), status_code=303)

    async def status(request: Request) -> Response:
        job = jobs.get(request.path_params["job_id"])
        if job is None:
            return RedirectResponse(request.url_for("index"), status_code=303)
        return TEMPLATES.TemplateResponse(request, "status.html", {"job": job})

    async def board(request: Request) -> Response:
        proposals = await asyncio.to_thread(store.list_proposals)
        return TEMPLATES.TemplateResponse(
            request, "board.html", {"proposals": proposals, "catalog": catalog}
        )

    return [
        Route("/", index, name="index"),
        Route("/propose", propose, methods=["POST"], name="propose"),
        Route("/status/{job_id}", status, name="status"),
        Route("/board", board, name="board"),
    ]
