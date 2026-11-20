"""The client side of OAuth: sign the organizer in and collect their tokens.

This is the piece of "MCP servers with OAuth credentials passed from the client":

1. Our client (this CLI) sends the organizer to the authorization server.
2. The organizer signs in and approves.
3. We exchange the returned code for an access token and a refresh token.
4. We store both in a vault (``vaults.store_calendar_oauth``).
5. Sessions attach the vault; Anthropic sends the token to the Calendar MCP server and
   refreshes it when it expires.

The flow is the standard authorization-code grant with PKCE for a public client.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from concierge.config import Settings
from concierge.vaults import OAUTH_CLIENT_ID

CALLBACK_PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}/callback"
SCOPE = "calendar.read calendar.write"


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def make_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for the S256 method."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(settings: Settings, *, state: str, code_challenge: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{settings.oauth_authorize_endpoint}?{query}"


def _wait_for_callback(expected_state: str) -> str:
    """Run a one-request local web server and return the authorization code."""
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            params = parse_qs(urlsplit(self.path).query)
            received["code"] = params.get("code", [""])[0]
            received["state"] = params.get("state", [""])[0]
            received["error"] = params.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Signed in. You can close this tab.</h2>")

        def log_message(self, format: str, *args: object) -> None:
            return  # keep the terminal quiet

    with HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler) as server:
        server.timeout = 300
        server.handle_request()

    if received.get("error"):
        raise RuntimeError(f"Sign-in was refused: {received['error']}")
    # The state value ties the callback to the request we started (CSRF protection).
    if not received.get("code") or not secrets.compare_digest(
        received.get("state", ""), expected_state
    ):
        raise RuntimeError("Sign-in did not complete: missing code or mismatched state.")
    return received["code"]


def sign_in(settings: Settings, *, open_browser: bool = True) -> OAuthTokens:
    """Run the whole sign-in and return the organizer's tokens."""
    # Guide 07 · Passing OAuth credentials from the client to an MCP server · Step 2:
    # start the authorization-code flow with PKCE.
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(16)
    url = build_authorize_url(settings, state=state, code_challenge=challenge)
    print(f"Open this address to sign in as the organizer:\n  {url}\n")
    if open_browser:
        webbrowser.open(url)
    code = _wait_for_callback(state)

    # Guide 07 · Step 3: exchange the code (plus the PKCE verifier) for tokens.
    response = httpx.post(
        settings.oauth_token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": OAUTH_CLIENT_ID,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_in=int(payload["expires_in"]),
    )
