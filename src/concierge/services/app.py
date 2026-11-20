"""Assemble the mock services (and, optionally, the proposal portal) into one ASGI app.

One app means one port and one public tunnel. Each service still lives in its own module.
"""

from __future__ import annotations

import contextlib
import secrets
from collections.abc import AsyncIterator

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.types import ASGIApp

from concierge.catalog import Catalog, get_catalog
from concierge.config import Settings, get_settings
from concierge.services import credits_api, oauth
from concierge.services.auth import BearerAuthMiddleware
from concierge.services.calendar_mcp import build_calendar_server
from concierge.services.eventdb_mcp import build_eventdb_server
from concierge.services.mcp_edge import McpEdgeMiddleware
from concierge.services.store import Store


def _mcp_asgi(server: MCPServer) -> ASGIApp:
    """Serve an MCP server over Streamable HTTP at ``<mount>/mcp``."""
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,  # no server-side sessions: simplest behind a tunnel
        json_response=True,
        # The app is reached through a tunnel under a public hostname, so the localhost-only
        # Host check does not apply. The bearer-token middleware is what protects it.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def build_app(
    settings: Settings | None = None,
    *,
    catalog: Catalog | None = None,
    extra_routes: list[BaseRoute] | None = None,
) -> Starlette:
    settings = settings or get_settings()
    catalog = catalog or get_catalog()
    store = Store(settings.db_path)

    eventdb = build_eventdb_server(store, catalog)
    calendar = build_calendar_server(store)

    def verify_static_token(token: str) -> str | None:
        return "eventdb-client" if secrets.compare_digest(token, settings.eventdb_token) else None

    verify_oauth_token = oauth.make_access_token_verifier(store)

    def verify_calendar_token(token: str) -> str | None:
        """Accept an OAuth access token, or (phase 2b only) the configured static token."""
        static = settings.calendar_static_token
        if static and secrets.compare_digest(token, static):
            return "organizer (static token)"
        return verify_oauth_token(token)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        # Mounted sub-apps do not run their own lifespans, so start both MCP servers here.
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(eventdb.session_manager.run())
            await stack.enter_async_context(calendar.session_manager.run())
            yield

    async def health(request: object) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    routes: list[BaseRoute] = [
        Route("/healthz", health),
        *oauth.build_routes(settings, store),
        *credits_api.build_routes(settings, store),
        # Guide 06 · Storing secrets in a vault · Step 6: the server side of a static bearer
        Mount(
            "/eventdb",
            app=McpEdgeMiddleware(
                BearerAuthMiddleware(
                    _mcp_asgi(eventdb), verify=verify_static_token, realm="eventdb"
                ),
                name="eventdb",
            ),
        ),
        # Guide 07 · Passing OAuth credentials from the client to an MCP server · Step 6:
        # the MCP server accepts only access tokens our authorization server issued.
        Mount(
            "/calendar",
            app=McpEdgeMiddleware(
                BearerAuthMiddleware(
                    _mcp_asgi(calendar),
                    verify=verify_calendar_token,
                    realm="calendar",
                ),
                name="calendar",
            ),
        ),
        *(extra_routes or []),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    app.state.catalog = catalog
    return app
