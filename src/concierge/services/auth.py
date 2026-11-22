"""Bearer-token checking for the mock services, as a small ASGI middleware."""

from __future__ import annotations

import contextvars
import logging
import sys
from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# uvicorn configures this logger, so the lines appear in the `concierge serve` terminal.
logger = logging.getLogger("uvicorn.error")

# Every line about OAuth use starts with this, so students can spot it or grep for it.
OAUTH_MARKER = "========== OAUTH =========="


def log_oauth(kind: str, message: str, *, warning: bool = False) -> None:
    """Log one OAuth event under the big OAUTH marker. Never pass a token, code or password.

    ``kind`` is SIGN-IN, MCP CALL, REFRESH or REFUSED. In a terminal the marker is shown in
    bold yellow; in a file or a test it is plain text.
    """
    marker = OAUTH_MARKER
    if sys.stderr.isatty():
        marker = f"\033[1;33m{marker}\033[0m"
    line = f"{marker} {kind}: {message}"
    (logger.warning if warning else logger.info)(line)


# Who the current request acts as (for example "organizer"), for tools that need to know.
current_subject: contextvars.ContextVar[str] = contextvars.ContextVar("current_subject")

# A verifier takes the presented token and returns the subject it belongs to, or None.
TokenVerifier = Callable[[str], str | None]


class BearerAuthMiddleware:
    """Reject requests without a valid ``Authorization: Bearer <token>`` header."""

    def __init__(self, app: ASGIApp, *, verify: TokenVerifier, realm: str) -> None:
        self.app = app
        self.verify = verify
        self.realm = realm

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        scheme, _, token = headers.get(b"authorization", b"").decode("latin-1").partition(" ")
        subject = self.verify(token.strip()) if scheme.lower() == "bearer" and token else None
        if subject is None:
            response = JSONResponse(
                {"error": "invalid_token"},
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer realm="{self.realm}", error="invalid_token"'},
            )
            await response(scope, receive, send)
            return
        reset_token = current_subject.set(subject)
        try:
            await self.app(scope, receive, send)
        finally:
            current_subject.reset(reset_token)
