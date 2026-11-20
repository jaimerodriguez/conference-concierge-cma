"""Settings, loaded from the environment and an optional ``.env`` file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

PLACEHOLDER_HOST = "concierge.example.com"


class Settings(BaseSettings):
    """Everything the demo reads from the environment.

    Only ``CONCIERGE_*`` variables are read here. The Claude SDK reads its own credentials
    (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile) by itself.
    """

    model_config = SettingsConfigDict(
        env_prefix="CONCIERGE_",
        # Anchored to the repo, not the current directory, so every command behaves the same
        # from the repo root, from managed/ (where `ant apply` runs), or anywhere else.
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    workspace: str = "default"
    public_base_url: str = f"https://{PLACEHOLDER_HOST}"
    organizer_password: str = "change-me"
    eventdb_token: str = "change-me"
    cloudcredits_api_key: str = "change-me"
    timezone: str = "America/Los_Angeles"
    db_path: Path = Path(".concierge/concierge.db")
    state_path: Path = Path(".concierge/state.json")
    otel_content_mode: str = "metadata_only"

    # Which environment sessions run in: the file name under managed/environments/
    # ("cloud" for phase 1, "self-hosted" for phase 2a). `environment_id` wins when set, for
    # an environment that `ant apply` does not manage (phase 2b).
    environment: str = "cloud"
    environment_id: str | None = None

    # Phase 2b only: a fixed token the Calendar MCP server also accepts, because a
    # self-hosted server has no OAuth refresh flow. Unset means OAuth only.
    calendar_static_token: str | None = None

    managed_dir: Path = Field(default=REPO_ROOT / "managed")
    content_dir: Path = Field(default=REPO_ROOT / "content")

    # Pin the Attendee Helper to one agent version (Guide 02). Unset means "latest".
    helper_agent_version: int | None = None

    # Session budgets in US cents (Guide 12).
    proposal_budget_cents: int = 50
    helper_budget_cents: int = 25
    agenda_budget_cents: int = 500

    @field_validator("db_path", "state_path", "managed_dir", "content_dir", mode="after")
    @classmethod
    def _relative_to_repo(cls, path: Path) -> Path:
        """A relative path in ``.env`` means relative to the repo root, wherever you run from."""
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def base_url(self) -> str:
        return self.public_base_url.rstrip("/")

    @property
    def public_host(self) -> str:
        return urlsplit(self.base_url).netloc

    @property
    def eventdb_mcp_url(self) -> str:
        return f"{self.base_url}/eventdb/mcp"

    @property
    def calendar_mcp_url(self) -> str:
        return f"{self.base_url}/calendar/mcp"

    @property
    def credits_api_url(self) -> str:
        return f"{self.base_url}/credits/api"

    @property
    def oauth_token_endpoint(self) -> str:
        return f"{self.base_url}/oauth/token"

    @property
    def oauth_authorize_endpoint(self) -> str:
        return f"{self.base_url}/oauth/authorize"


@lru_cache
def get_settings() -> Settings:
    return Settings()
