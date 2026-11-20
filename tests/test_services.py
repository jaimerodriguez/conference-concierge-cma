"""End-to-end tests of the mock services: OAuth, both MCP servers, and the sponsor API."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from concierge.config import Settings
from concierge.oauth_client import REDIRECT_URI, SCOPE, make_pkce_pair
from concierge.vaults import OAUTH_CLIENT_ID
from tests.conftest import MCP_HEADERS, call_tool


def sign_in(client: TestClient, settings: Settings) -> dict[str, str]:
    """Run the authorization-code + PKCE flow the way the CLI does."""
    verifier, challenge = make_pkce_pair()
    form = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": "state-123",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    assert client.get("/oauth/authorize", params=form).status_code == 200
    approved = client.post(
        "/oauth/authorize", data={**form, "password": settings.organizer_password}
    )
    assert approved.status_code == 303
    query = parse_qs(urlsplit(approved.headers["location"]).query)
    assert query["state"] == ["state-123"]
    tokens = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": REDIRECT_URI,
            "client_id": OAUTH_CLIENT_ID,
            "code_verifier": verifier,
        },
    )
    assert tokens.status_code == 200, tokens.text
    return tokens.json()


def test_mcp_servers_reject_missing_or_wrong_tokens(client: TestClient) -> None:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert client.post("/eventdb/mcp", json=body, headers=MCP_HEADERS).status_code == 401
    wrong = {**MCP_HEADERS, "Authorization": "Bearer nope"}
    assert client.post("/calendar/mcp", json=body, headers=wrong).status_code == 401


def test_oauth_wrong_password_shows_form_again(client: TestClient) -> None:
    _, challenge = make_pkce_pair()
    response = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "password": "wrong",
        },
    )
    assert response.status_code == 200
    assert "not right" in response.text


def test_oauth_code_is_single_use_and_needs_the_verifier(
    client: TestClient, settings: Settings
) -> None:
    _, challenge = make_pkce_pair()
    form = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": "s",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "password": settings.organizer_password,
    }
    location = client.post("/oauth/authorize", data=form).headers["location"]
    code = parse_qs(urlsplit(location).query)["code"][0]
    exchange = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": OAUTH_CLIENT_ID,
        "code_verifier": "not-the-verifier",
    }
    assert client.post("/oauth/token", data=exchange).json()["error"] == "invalid_grant"
    # The failed attempt consumed the code, so it cannot be replayed.
    assert client.post("/oauth/token", data=exchange).json()["error"] == "invalid_grant"


def test_calendar_booking_with_oauth_token_and_refresh(
    client: TestClient, settings: Settings
) -> None:
    tokens = sign_in(client, settings)
    booked = call_tool(
        client,
        "calendar",
        tokens["access_token"],
        "create_event",
        {
            "title": "Opening talk",
            "room": "Main Hall",
            "starts_at": "2026-12-10T18:30",
            "ends_at": "2026-12-10T18:55",
        },
    )
    event = booked["result"]["structuredContent"]
    assert event["created_by"] == "organizer"  # the token says who is acting

    clash = call_tool(
        client,
        "calendar",
        tokens["access_token"],
        "create_event",
        {
            "title": "Clash",
            "room": "Main Hall",
            "starts_at": "2026-12-10T18:40",
            "ends_at": "2026-12-10T19:00",
        },
    )
    assert clash["result"]["isError"] is True

    slots = call_tool(
        client,
        "calendar",
        tokens["access_token"],
        "find_free_slots",
        {
            "room": "Main Hall",
            "date": "2026-12-10",
            "window_start": "18:30",
            "window_end": "19:30",
            "minutes": 25,
        },
    )
    starts = [slot["starts_at"] for slot in slots["result"]["structuredContent"]["result"]]
    assert starts == ["2026-12-10T18:55"]

    # The refresh grant is what Anthropic calls when the vaulted access token expires.
    refresh = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": OAUTH_CLIENT_ID,
    }
    renewed = client.post("/oauth/token", data=refresh)
    assert renewed.status_code == 200
    assert renewed.json()["access_token"] != tokens["access_token"]
    # Refresh tokens rotate: the old one no longer works.
    assert client.post("/oauth/token", data=refresh).json()["error"] == "invalid_grant"


def test_proposal_review_acceptance_and_perk(client: TestClient, settings: Settings) -> None:
    store = client.app.state.store
    member = store.add_member("sam@example.com", persona="weekend-hacker")
    proposal = store.add_proposal(
        member_id=member["id"],
        event_id="event",
        track="fun",
        format="lightning",
        title="Bunnies",
        abstract="A talk about bunnies.",
        source="predefined_topic",
    )
    token = settings.eventdb_token

    submitted = call_tool(client, "eventdb", token, "list_proposals", {"status": "submitted"})
    assert len(submitted["result"]["structuredContent"]["result"]) == 1

    reviewed = call_tool(
        client,
        "eventdb",
        token,
        "record_review",
        {
            "proposal_id": proposal["id"],
            "scores": {"clarity": 5, "takeaway": 4},
            "overall": 4.5,
            "recommendation": "accept",
            "summary": "Clear and fun.",
        },
    )
    # A review never accepts: it only moves the proposal to "reviewed".
    assert reviewed["result"]["structuredContent"]["status"] == "reviewed"

    bad = call_tool(
        client,
        "eventdb",
        token,
        "record_review",
        {
            "proposal_id": proposal["id"],
            "scores": {"clarity": 9},
            "overall": 9,
            "recommendation": "accept",
            "summary": "x",
        },
    )
    assert bad["result"]["isError"] is True

    perk_request = {"member_id": member["id"], "amount_usd": 50}
    key = {"X-Api-Key": settings.cloudcredits_api_key}
    # Not a speaker yet, so no perk.
    assert client.post("/credits/api/codes", json=perk_request, headers=key).status_code == 403

    call_tool(
        client,
        "eventdb",
        token,
        "set_proposal_status",
        {"proposal_id": proposal["id"], "status": "accepted"},
    )
    assert "speaker" in store.get_member(member["id"])["roles"]

    assert client.post("/credits/api/codes", json=perk_request).status_code == 401
    first = client.post("/credits/api/codes", json=perk_request, headers=key).json()
    second = client.post("/credits/api/codes", json=perk_request, headers=key).json()
    assert first["code"] == second["code"]  # issuing is idempotent

    recorded = call_tool(
        client, "eventdb", token, "record_perk", {"member_id": member["id"], "code": first["code"]}
    )
    assert recorded["result"]["structuredContent"]["recorded"] == 1


def test_portal_pages_render(settings: Settings) -> None:
    from concierge.catalog import load_catalog
    from concierge.config import REPO_ROOT
    from concierge.portal.app import build_routes
    from concierge.services.app import build_app
    from concierge.services.store import Store

    catalog = load_catalog(REPO_ROOT / "content")
    routes = build_routes(settings, Store(settings.db_path), catalog)
    with TestClient(build_app(settings, catalog=catalog, extra_routes=routes)) as portal:
        form = portal.get("/")
        assert form.status_code == 200 and catalog.topics[0] in form.text
        assert "Submit talk proposal" in form.text and "Let AI generate abstract" in form.text
        assert portal.get("/board").status_code == 200
        good = {"contact_email": "sam@example.com", "persona": "weekend-hacker", "track": "fun"}
        # Every bad submission below is rejected before any model call is made.
        bad = portal.post("/propose", data={**good, "persona": "nope", "ai_abstract": "on"})
        assert bad.status_code == 400
        bad_email = portal.post("/propose", data={**good, "contact_email": "sam@", "topic": "x"})
        assert bad_email.status_code == 400 and "valid contact email" in bad_email.text
        # Unchecking "Let AI generate abstract" makes the title and abstract required...
        no_abstract = portal.post("/propose", data={**good, "title": "Mine", "topic": "x"})
        assert no_abstract.status_code == 400 and "abstract of at least" in no_abstract.text
        # ...and what was typed comes back, so nobody retypes it.
        assert 'value="Mine"' in no_abstract.text and 'value="sam@example.com"' in no_abstract.text


def test_board_groups_proposals_and_shows_feedback(settings: Settings) -> None:
    from concierge.catalog import load_catalog
    from concierge.config import REPO_ROOT
    from concierge.portal.app import build_routes
    from concierge.services.app import build_app
    from concierge.services.store import Store

    catalog = load_catalog(REPO_ROOT / "content")
    store = Store(settings.db_path)
    member = store.add_member("ada@example.com")
    titles = {}
    for status in ("accepted", "waitlisted", "declined", "submitted"):
        proposal = store.add_proposal(
            member_id=member["id"],
            event_id="e",
            track="ai-ml",
            format="talk",
            title=f"Talk {status}",
            abstract=f"Abstract for {status}.",
            source="sample",
        )
        if status != "submitted":
            store.record_review(
                proposal["id"],
                scores={"Clarity": 4},
                overall=4.0,
                recommendation="accept",
                summary=f"Feedback for {status}.",
            )
            store.set_proposal_status(proposal["id"], status)
        titles[status] = proposal["id"]

    routes = build_routes(settings, store, catalog)
    with TestClient(build_app(settings, catalog=catalog, extra_routes=routes)) as portal:
        page = portal.get("/board").text
    sections = {
        key: page.index(f'id="group-{key}"')
        for key in ("accepted", "reviewed", "declined", "submitted")
    }
    position = {status: page.index(f'id="{pid}"') for status, pid in titles.items()}
    assert sections["accepted"] < position["accepted"] < sections["reviewed"]
    assert sections["reviewed"] < position["waitlisted"] < sections["declined"]
    assert sections["declined"] < position["declined"] < sections["submitted"]
    assert position["submitted"] > sections["submitted"]
    assert "Not this time" in page and "Abstract for accepted." in page
    assert "Feedback for declined." in page and "Contact: a***@example.com" in page
    assert "ada@example.com" not in page  # the board never shows a full address


def test_board_masks_contact_emails() -> None:
    from concierge.portal.app import mask_email

    assert mask_email("ada.lovelace@example.com") == "ad***e@example.com"
    assert mask_email("juno@example.com") == "ju***o@example.com"
    assert mask_email("ada@example.com") == "a***@example.com"
    assert mask_email("not-an-address") == "***"


def _initialize(protocol_version: str = "2025-06-18") -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }


@pytest.mark.parametrize("mount", ["eventdb", "calendar"])
@pytest.mark.parametrize("header", [None, "2025-11-25", "2026-07-28", "2099-01-01"])
def test_initialize_succeeds_whatever_protocol_version_header_the_client_sends(
    client: TestClient, settings: Settings, mount: str, header: str | None
) -> None:
    token = (
        settings.eventdb_token if mount == "eventdb" else sign_in(client, settings)["access_token"]
    )
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
    if header:
        headers["MCP-Protocol-Version"] = header
    response = client.post(f"/{mount}/mcp", json=_initialize(), headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["serverInfo"]["name"] == mount


def test_mcp_failures_are_logged_without_the_token(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        client.post(
            "/eventdb/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={**MCP_HEADERS, "Authorization": "Bearer secret-value"},
        )
    assert "MCP eventdb: POST -> 401 rpc=tools/list" in caplog.text
    assert "secret-value" not in caplog.text
