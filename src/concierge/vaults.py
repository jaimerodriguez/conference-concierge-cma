"""Put the demo's credentials in a vault.

The vault itself is declared in ``managed/vaults/concierge.yaml``. Credentials are never
written to files: this module adds them through the SDK. Three kinds are shown:

=====================  ==================  ==============================================
Credential             Type                What it teaches
=====================  ==================  ==============================================
Event DB MCP server    ``static_bearer``   A fixed token for an MCP server
CloudCredits API key   ``environment_variable``  A secret the sandbox never sees
Calendar MCP server    ``mcp_oauth``       The organizer's own OAuth tokens (Guide 07)
=====================  ==================  ==============================================

Secret fields are write-only: the API never returns them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from anthropic import Anthropic

from concierge.config import Settings, get_settings
from concierge.managed import ManagedResources

CLOUDCREDITS_SECRET_NAME = "CLOUDCREDITS_API_KEY"
OAUTH_CLIENT_ID = "concierge-cli"


def _upsert_credential(
    client: Anthropic,
    vault_id: str,
    *,
    matches: Callable[[Any], bool],
    display_name: str,
    create_auth: dict[str, Any],
    update_auth: dict[str, Any],
) -> str:
    """Create the credential, or rotate its secret when it already exists.

    A vault allows one active credential per key (MCP server URL or secret name), so a
    second ``create`` would fail with 409. Rotating in place is also what you do in real life.
    """
    for credential in client.beta.vaults.credentials.list(vault_id):
        if matches(credential.auth):
            client.beta.vaults.credentials.update(
                credential.id, vault_id=vault_id, auth=update_auth
            )
            return f"rotated {display_name}"
    client.beta.vaults.credentials.create(vault_id, display_name=display_name, auth=create_auth)
    return f"created {display_name}"


def store_eventdb_token(client: Anthropic, vault_id: str, settings: Settings) -> str:
    """Guide 06 · Storing secrets in a vault · Step 2: a static bearer token for an MCP server

    MCP credentials are matched to an agent's MCP server by URL. The agent file only names
    the server; the token is added to the request by Anthropic's proxy, outside the sandbox.
    """
    url = settings.eventdb_mcp_url
    return _upsert_credential(
        client,
        vault_id,
        matches=lambda auth: getattr(auth, "mcp_server_url", None) == url,
        display_name="Event DB (static bearer)",
        create_auth={
            "type": "static_bearer",
            "mcp_server_url": url,
            "token": settings.eventdb_token,
        },
        update_auth={"type": "static_bearer", "token": settings.eventdb_token},
    )


def store_cloudcredits_key(client: Anthropic, vault_id: str, settings: Settings) -> str:
    """Guide 06 · Storing secrets in a vault · Step 3: an environment-variable secret

    The sandbox sees ``$CLOUDCREDITS_API_KEY`` as an opaque placeholder. The real value is
    substituted after the request leaves the sandbox, only on requests to ``allowed_hosts``
    and only in the places ``injection_location`` allows (here: headers, not the body).
    """
    return _upsert_credential(
        client,
        vault_id,
        matches=lambda auth: getattr(auth, "secret_name", None) == CLOUDCREDITS_SECRET_NAME,
        display_name="CloudCredits sponsor API key",
        create_auth={
            "type": "environment_variable",
            "secret_name": CLOUDCREDITS_SECRET_NAME,
            "secret_value": settings.cloudcredits_api_key,
            "networking": {"type": "limited", "allowed_hosts": [settings.public_host]},
            "injection_location": {"header": True, "body": False},
        },
        # Rotating also resets the hosts and injection place, so a credential created for an
        # earlier tunnel address does not keep that address (it replaces them as a whole).
        update_auth={
            "type": "environment_variable",
            "secret_value": settings.cloudcredits_api_key,
            "networking": {"type": "limited", "allowed_hosts": [settings.public_host]},
            "injection_location": {"header": True, "body": False},
        },
    )


def store_calendar_oauth(
    client: Anthropic,
    vault_id: str,
    settings: Settings,
    *,
    access_token: str,
    refresh_token: str,
    expires_in: int,
) -> str:
    """Guide 07 · Passing OAuth credentials from the client to an MCP server · Step 4

    Store the organizer's tokens. The ``refresh`` block is what lets Anthropic renew the
    access token on its own: it posts a standard ``refresh_token`` grant to our token endpoint.
    """
    url = settings.calendar_mcp_url
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
    return _upsert_credential(
        client,
        vault_id,
        matches=lambda auth: getattr(auth, "mcp_server_url", None) == url,
        display_name="Calendar (organizer OAuth)",
        create_auth={
            "type": "mcp_oauth",
            "mcp_server_url": url,
            "access_token": access_token,
            "expires_at": expires_at,
            "refresh": {
                "refresh_token": refresh_token,
                "client_id": OAUTH_CLIENT_ID,
                "token_endpoint": settings.oauth_token_endpoint,
                # A public client (PKCE, no client secret), like a CLI or a mobile app.
                "token_endpoint_auth": {"type": "none"},
            },
        },
        update_auth={
            "type": "mcp_oauth",
            "access_token": access_token,
            "expires_at": expires_at,
            "refresh": {"refresh_token": refresh_token},
        },
    )


def store_calendar_static_token(client: Anthropic, vault_id: str, settings: Settings) -> str:
    """Phase 2b fallback (Guide 21): a self-hosted server rejects ``mcp_oauth`` credentials,
    so the Calendar gets a fixed token that you must rotate yourself."""
    url = settings.calendar_mcp_url
    token = settings.calendar_static_token or ""
    return _upsert_credential(
        client,
        vault_id,
        matches=lambda auth: getattr(auth, "mcp_server_url", None) == url,
        display_name="Calendar (static bearer, rotate by hand)",
        create_auth={"type": "static_bearer", "mcp_server_url": url, "token": token},
        update_auth={"type": "static_bearer", "token": token},
    )


def remove_cloudcredits_key(client: Anthropic, vault_id: str) -> str:
    """Guide 20 · Moving tools into your own sandbox · Step 3: take the egress secret out

    A session in a self-hosted environment is refused if its vault holds any
    ``environment_variable`` credential, so the key stored for phase 1 has to go. The value
    stays in your .env: run ``setup vault`` with ``CONCIERGE_ENVIRONMENT=cloud`` to put it back.
    """
    removed = 0
    for credential in client.beta.vaults.credentials.list(vault_id):
        if getattr(credential.auth, "type", None) == "environment_variable":
            client.beta.vaults.credentials.delete(credential.id, vault_id=vault_id)
            removed += 1
    if removed:
        return (
            "removed CloudCredits key: self-hosted sessions refuse a vault with "
            "environment_variable credentials (setup vault in cloud mode puts it back)"
        )
    return "skipped CloudCredits key: not available outside the cloud sandbox"


def has_credential_for(client: Anthropic, url: str, settings: Settings | None = None) -> bool:
    """True when the vault already holds a credential for this MCP server URL."""
    from concierge.wiring import normalize_url

    settings = settings or get_settings()
    vault_id = ManagedResources(settings.managed_dir).vault_id()
    wanted = normalize_url(url)
    return any(
        normalize_url(str(getattr(credential.auth, "mcp_server_url", "") or "")) == wanted
        for credential in client.beta.vaults.credentials.list(vault_id)
    )


def find_stale_credentials(client: Anthropic, settings: Settings | None = None) -> list[Any]:
    """MCP credentials stored for a server URL this app no longer uses (e.g. an old tunnel).

    Only credentials with an MCP server URL are considered; secrets are matched by name and
    never listed here. They are ignored by sessions, so keeping them is harmless.
    """
    from concierge.wiring import expected_urls, normalize_url

    settings = settings or get_settings()
    vault_id = ManagedResources(settings.managed_dir).vault_id()
    current = {normalize_url(url) for url in expected_urls(settings).values()}
    return [
        credential
        for credential in client.beta.vaults.credentials.list(vault_id)
        if getattr(credential.auth, "mcp_server_url", None)
        and normalize_url(credential.auth.mcp_server_url) not in current
    ]


def store_static_secrets(client: Anthropic, settings: Settings | None = None) -> list[str]:
    """Add (or rotate) the two credentials that need no sign-in."""
    settings = settings or get_settings()
    vault_id = ManagedResources(settings.managed_dir).vault_id()
    results = [store_eventdb_token(client, vault_id, settings)]
    if settings.environment == "cloud" and not settings.environment_id:
        results.append(store_cloudcredits_key(client, vault_id, settings))
    else:
        # Environment-variable credentials need Anthropic-managed egress (Guides 20 and 21).
        results.append(remove_cloudcredits_key(client, vault_id))
    if settings.calendar_static_token:
        results.append(store_calendar_static_token(client, vault_id, settings))
    return results
