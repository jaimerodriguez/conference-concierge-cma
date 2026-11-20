"""A thin ASGI layer in front of the mock MCP servers: request log and handshake tolerance.

Anthropic's MCP proxy is the client of these servers, and a client you do not control is where
"HTTP 400" comes from. This layer does two small things:

* It logs every MCP request's outcome (status, JSON-RPC method, protocol-version header and,
  for 4xx/5xx answers, the start of the body), through uvicorn's logger so it shows up in the
  terminal that runs ``concierge serve``. It never logs the ``Authorization`` header.
* The MCP SDK routes a request by its ``MCP-Protocol-Version`` header: a value it does not
  list as a handshake-era revision goes to the newer, stateless path, which wants a
  ``params._meta`` envelope that an ``initialize`` request does not carry, and answers 400.
  For an ``initialize`` request, this layer drops such a header, so the ordinary handshake
  runs. Every other request passes through untouched.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# uvicorn configures this logger, so the lines appear without any logging setup.
logger = logging.getLogger("uvicorn.error")

VERSION_HEADER = b"mcp-protocol-version"
MAX_BODY = 1_000_000
SHOWN_HEADERS = (b"mcp-protocol-version", b"mcp-session-id", b"accept", b"content-type")


class McpEdgeMiddleware:
    def __init__(self, app: ASGIApp, *, name: str) -> None:
        self.app = app
        self.name = name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        body = b""
        if scope["method"] == "POST":
            body = await _read_body(receive)
            receive = _replay(body)
        rpc = _parse(body)
        dropped_version: str | None = None

        if rpc.get("method") == "initialize":
            kept = []
            for key, value in scope["headers"]:
                if key == VERSION_HEADER and value.decode("latin-1") not in (
                    HANDSHAKE_PROTOCOL_VERSIONS
                ):
                    dropped_version = value.decode("latin-1")
                    continue
                kept.append((key, value))
            if dropped_version is not None:
                scope = {**scope, "headers": kept}

        status = 0

        async def send_and_note(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, receive, send_and_note)

        headers = {
            key.decode(): value.decode("latin-1")
            for key, value in scope["headers"]
            if key in SHOWN_HEADERS
        }
        line = (
            f"MCP {self.name}: {scope['method']} -> {status} "
            f"rpc={rpc.get('method', '-')} headers={headers}"
        )
        if dropped_version is not None:
            line += f" (ignored MCP-Protocol-Version {dropped_version} on initialize)"
        if status >= 400:
            logger.warning("%s body=%r", line, body[:500].decode("utf-8", "replace"))
        else:
            logger.info(line)


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":  # a disconnect: stop reading
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size <= MAX_BODY:
            chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _replay(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _parse(body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
