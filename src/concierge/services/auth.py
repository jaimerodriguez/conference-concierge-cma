"""Bearer-token checking for the mock services, as a small ASGI middleware."""

from __future__ import annotations

import contextvars
from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

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
