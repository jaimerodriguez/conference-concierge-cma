"""A tiny OAuth 2.0 authorization server, just enough to teach the flow.

It supports what the demo needs and nothing more:

* the authorization-code grant with PKCE (S256) for one public client, and
* the refresh-token grant, with refresh-token rotation.

The "sign-in" is a single shared organizer password. A real system would use your identity
provider here. Do not reuse this code for anything real.
"""

from __future__ import annotations

import base64
import hashlib
import html
import secrets
import time
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from concierge.config import Settings
from concierge.services.store import Store

CLIENT_ID = "concierge-cli"
ALLOWED_REDIRECT_PREFIXES = ("http://127.0.0.1:", "http://localhost:")
ACCESS_TOKEN_TTL_SECONDS = 15 * 60  # short on purpose, so the demo shows a refresh
AUTH_CODE_TTL_SECONDS = 120
SUBJECT = "organizer"

_FORM = """<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in</title>
<body style="font-family: system-ui; max-width: 26rem; margin: 3rem auto; padding: 0 1rem">
<h2>AI Meetup</h2>
<p><b>Conference Concierge</b> wants to read and book events on the organizer's calendar.</p>
{error}
<form method="post">
  {hidden}
  <label>Organizer password<br><input type="password" name="password" autofocus></label>
  <p><button type="submit">Sign in and allow</button></p>
</form>
</body>"""

_PARAMS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "scope",
    "state",
    "code_challenge",
    "code_challenge_method",
)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


def build_routes(settings: Settings, store: Store) -> list[Route]:
    def validate_request(params: dict[str, str]) -> str | None:
        if params.get("response_type") != "code":
            return "response_type must be 'code'"
        if params.get("client_id") != CLIENT_ID:
            return "unknown client_id"
        if not params.get("redirect_uri", "").startswith(ALLOWED_REDIRECT_PREFIXES):
            return "redirect_uri must be a loopback address"
        if params.get("code_challenge_method") != "S256" or not params.get("code_challenge"):
            return "PKCE with S256 is required"
        return None

    def render_form(params: dict[str, str], error: str = "") -> HTMLResponse:
        hidden = "\n".join(
            f'<input type="hidden" name="{name}" value="{html.escape(params.get(name, ""))}">'
            for name in _PARAMS
        )
        error_html = f'<p style="color: #b00020">{html.escape(error)}</p>' if error else ""
        return HTMLResponse(_FORM.format(hidden=hidden, error=error_html))

    async def authorize(request: Request) -> Response:
        if request.method == "GET":
            params = {name: request.query_params.get(name, "") for name in _PARAMS}
            problem = validate_request(params)
            return (
                HTMLResponse(html.escape(problem), status_code=400)
                if problem
                else render_form(params)
            )

        form = await request.form()
        params = {name: str(form.get(name, "")) for name in _PARAMS}
        problem = validate_request(params)
        if problem:
            return HTMLResponse(html.escape(problem), status_code=400)
        password = str(form.get("password", ""))
        if not secrets.compare_digest(password, settings.organizer_password):
            return render_form(params, error="That password is not right.")

        code = secrets.token_urlsafe(32)
        store.save_oauth_code(
            code=code,
            client_id=CLIENT_ID,
            redirect_uri=params["redirect_uri"],
            code_challenge=params["code_challenge"],
            scope=params["scope"],
            subject=SUBJECT,
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
        )
        query = urlencode({"code": code, "state": params["state"]})
        return RedirectResponse(f"{params['redirect_uri']}?{query}", status_code=303)

    def issue_tokens(scope: str, subject: str) -> JSONResponse:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        store.save_oauth_token(
            token=access_token,
            kind="access",
            client_id=CLIENT_ID,
            scope=scope,
            subject=subject,
            expires_at=time.time() + ACCESS_TOKEN_TTL_SECONDS,
        )
        store.save_oauth_token(
            token=refresh_token,
            kind="refresh",
            client_id=CLIENT_ID,
            scope=scope,
            subject=subject,
            expires_at=None,
        )
        return JSONResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": ACCESS_TOKEN_TTL_SECONDS,
                "refresh_token": refresh_token,
                "scope": scope,
            },
            headers={"Cache-Control": "no-store"},
        )

    async def token(request: Request) -> Response:
        form = await request.form()
        grant_type = form.get("grant_type")
        if form.get("client_id") != CLIENT_ID:
            return _oauth_error("invalid_client", "unknown client_id", status=401)

        if grant_type == "authorization_code":
            grant = store.take_oauth_code(str(form.get("code", "")))
            if grant is None or grant["redirect_uri"] != form.get("redirect_uri"):
                return _oauth_error("invalid_grant", "code is invalid, expired, or already used")
            verifier = str(form.get("code_verifier", ""))
            if not secrets.compare_digest(_pkce_challenge(verifier), grant["code_challenge"]):
                return _oauth_error("invalid_grant", "PKCE verification failed")
            return issue_tokens(grant["scope"], grant["subject"])

        if grant_type == "refresh_token":
            # This is the call Anthropic makes for us when a vaulted access token expires.
            presented = str(form.get("refresh_token", ""))
            grant = store.get_oauth_token(presented, "refresh")
            if grant is None:
                return _oauth_error("invalid_grant", "refresh token is invalid")
            store.delete_oauth_token(presented)  # rotation: each refresh token works once
            return issue_tokens(grant["scope"], grant["subject"])

        return _oauth_error("unsupported_grant_type", f"unsupported grant_type {grant_type!r}")

    async def metadata(request: Request) -> Response:
        return JSONResponse(
            {
                "issuer": settings.base_url,
                "authorization_endpoint": settings.oauth_authorize_endpoint,
                "token_endpoint": settings.oauth_token_endpoint,
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
            }
        )

    return [
        Route("/oauth/authorize", authorize, methods=["GET", "POST"]),
        Route("/oauth/token", token, methods=["POST"]),
        Route("/.well-known/oauth-authorization-server", metadata, methods=["GET"]),
    ]


def make_access_token_verifier(store: Store):
    """Return a verifier that accepts unexpired OAuth access tokens."""

    def verify(token: str) -> str | None:
        grant = store.get_oauth_token(token, "access")
        return grant["subject"] if grant else None

    return verify
