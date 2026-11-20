from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from concierge.catalog import load_catalog
from concierge.config import REPO_ROOT, Settings
from concierge.services.app import build_app

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        public_base_url="https://demo.test",
        organizer_password="open-sesame",
        eventdb_token="eventdb-token",
        cloudcredits_api_key="credits-key",
        db_path=tmp_path / "concierge.db",
        state_path=tmp_path / "state.json",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = build_app(settings, catalog=load_catalog(REPO_ROOT / "content"))
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


def call_tool(
    client: TestClient, mount: str, token: str, name: str, arguments: dict[str, object]
) -> dict[str, object]:
    """Call one MCP tool over Streamable HTTP and return the JSON-RPC response body."""
    response = client.post(
        f"/{mount}/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()
