"""Where the server URLs live, and whether they agree.

The mock services answer at one public address. That address is written down in several
places, and a mistake in any one of them breaks a run in a way that is hard to trace:

* ``.env``: ``CONCIERGE_PUBLIC_BASE_URL`` (what this code builds URLs from)
* the state file: the host ``concierge setup host`` last wrote
* the files under ``managed/`` (and the generated phase 2b copies)
* the agents as ``ant apply`` stored them in your workspace
* the credentials in the vault, which are matched to an agent's MCP server by URL

``check_local`` reads the files. ``check_remote`` also asks the API what is stored (secrets
are write-only, so they are never returned and never shown).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from concierge.config import REPO_ROOT, Settings
from concierge.managed import ManagedResources, NotAppliedError
from concierge.state import load_state

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SERVICE_URL = re.compile(r"https?://([A-Za-z0-9.-]+(?::\d+)?)/(?:eventdb|calendar|credits)\b")
ALLOWED_HOSTS = re.compile(r"allowed_hosts:\s*\[([^\]]*)\]")


@dataclass(frozen=True)
class Finding:
    """One result. ``ok`` is None when the check could not be made."""

    ok: bool | None
    label: str
    detail: str = ""
    fix: str = ""
    harmless: bool = False  # shown as a note: worth knowing, does not stop anything


@dataclass(frozen=True)
class Row:
    """One place a URL or host lives, for the "what points where" table."""

    place: str
    value: str


def normalize_url(url: str) -> str:
    """Compare URLs the way the vault does: lowercase scheme and host, no default port, no
    trailing slash."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    default = {"https": 443, "http": 80}.get(scheme)
    netloc = host if port in (None, default) else f"{host}:{port}"
    return f"{scheme}://{netloc}{parts.path.rstrip('/')}"


def hosts_in_files(root: Path) -> set[str]:
    """Hosts that agent and environment files use for the mock services."""
    found: set[str] = set()
    if not root.exists():
        return found
    for folder in ("agents", "environments"):
        for path in sorted((root / folder).rglob("*")):
            if path.suffix not in {".md", ".yaml"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            found.update(match.lower() for match in SERVICE_URL.findall(text))
            for group in ALLOWED_HOSTS.findall(text):
                found.update(h.strip().strip("'\"").lower() for h in group.split(",") if h.strip())
    return found


def expected_urls(settings: Settings) -> dict[str, str]:
    """The MCP server URLs this code believes in, by server name."""
    return {"eventdb": settings.eventdb_mcp_url, "calendar": settings.calendar_mcp_url}


PHASE_2B_DIR = REPO_ROOT / "phase2" / "b-self-hosted-service" / "managed"


def check_local(
    settings: Settings, phase_2b_dir: Path = PHASE_2B_DIR
) -> tuple[list[Row], list[Finding]]:
    expected_host = settings.public_host.lower()
    scheme = urlsplit(settings.base_url).scheme.lower()
    state_host = load_state(settings.state_path).get("managed_host")
    file_hosts = hosts_in_files(settings.managed_dir)
    phase2b_hosts = hosts_in_files(phase_2b_dir)

    rows = [
        Row(".env  CONCIERGE_PUBLIC_BASE_URL", settings.base_url),
        Row("last `setup host`", state_host or "(never run)"),
        Row("files under managed/", ", ".join(sorted(file_hosts)) or "(none)"),
    ]
    if phase2b_hosts:
        rows.append(Row("phase 2b copies", ", ".join(sorted(phase2b_hosts))))

    findings: list[Finding] = []
    if scheme != "https" and expected_host.split(":")[0] not in LOCAL_HOSTS:
        findings.append(
            Finding(
                False,
                "the address in .env uses https",
                f"CONCIERGE_PUBLIC_BASE_URL is {settings.base_url}. The cloud only calls "
                "https, and vault credentials are matched by exact URL.",
                f"set CONCIERGE_PUBLIC_BASE_URL=https://{expected_host} in .env, restart "
                "`concierge serve`, then run `concierge setup vault`",
            )
        )
    if state_host is not None and state_host.lower() != expected_host:
        findings.append(
            Finding(
                False,
                "`setup host` used the host in .env",
                f"it last wrote {state_host}, but .env says {expected_host}",
                "run `uv run concierge setup host`, then `ant apply` from inside managed/",
            )
        )
    for label, hosts in (("managed/ files", file_hosts), ("phase 2b files", phase2b_hosts)):
        stray = hosts - {expected_host}
        if stray:
            findings.append(
                Finding(
                    False,
                    f"{label} use the host in .env",
                    f"they name {', '.join(sorted(stray))}, but .env says {expected_host}",
                    "run `uv run concierge setup host`, then `ant apply` from inside managed/",
                )
            )
    if not findings:
        findings.append(Finding(True, "the host agrees in .env, the state file, and the files"))
    findings += _deployment_file_finding(settings)
    return rows, findings


FILE_LABEL = "the deployment file attaches the vault"
APPLIED_LABEL = "the applied deployment attaches the vault"


def merge_deployment_findings(findings: list[Finding]) -> list[Finding]:
    """One problem, one todo: a file with no vault means the applied deployment has none too."""
    file_bad = any(f.ok is False and f.label == FILE_LABEL for f in findings)
    return [f for f in findings if not (file_bad and f.label == APPLIED_LABEL)]


def _deployment_file_finding(settings: Settings) -> list[Finding]:
    """The deployment (``review run``, the schedule) only gets a vault if its file lists it."""
    managed = ManagedResources(settings.managed_dir)
    try:
        vault_id = managed.vault_id()
        listed = managed.deployment_vault_ids()
    except (NotAppliedError, OSError):
        return []  # not applied yet: the "managed files applied" check already says so
    if vault_id in listed:
        return [Finding(True, FILE_LABEL)]
    return [
        Finding(
            False,
            FILE_LABEL,
            f"managed/deployments/daily-review.yaml has vault_ids {listed or 'empty'}, so "
            "`review run` and the schedule start sessions with no credentials (agents then "
            "fail with 'no credential is stored for this server URL')",
            "run `uv run concierge setup deployment`, then `ant apply` from inside managed/",
        )
    ]


def _mcp_urls(agent: Any) -> list[str]:
    urls = []
    for server in getattr(agent, "mcp_servers", None) or []:
        url = server.get("url") if isinstance(server, dict) else getattr(server, "url", None)
        if url:
            urls.append(str(url))
    return urls


def check_remote(client: Any, settings: Settings) -> tuple[list[Row], list[Finding]]:
    """Compare what the cloud stored (agents, vault) with what ``.env`` says."""
    managed = ManagedResources(settings.managed_dir)
    expected = {normalize_url(url): name for name, url in expected_urls(settings).items()}
    rows: list[Row] = []
    findings: list[Finding] = []

    # What each applied agent will call.
    called: dict[str, list[str]] = {}  # normalized url -> agent names
    agents_dir = settings.managed_dir / "agents"
    for path in sorted(agents_dir.glob("*/agent.md")) if agents_dir.exists() else []:
        name = path.parent.name
        try:
            agent = client.beta.agents.retrieve(managed.agent_id(name))
        except Exception as error:  # not applied yet, or an API problem: say which
            findings.append(Finding(None, f"agent {name} in your workspace", _short(error)))
            continue
        version = getattr(agent, "version", "?")
        urls = _mcp_urls(agent)
        rows.append(Row(f"agent {name} (v{version})", ", ".join(urls) or "(no MCP servers)"))
        for url in urls:
            called.setdefault(normalize_url(url), []).append(name)
            if normalize_url(url) not in expected:
                findings.append(
                    Finding(
                        False,
                        f"agent {name} calls the address in .env",
                        f"the applied agent (v{version}) calls {url}; .env expects "
                        f"{', '.join(expected_urls(settings).values())}",
                        "run `uv run concierge setup host`, then `ant apply` from inside managed/",
                    )
                )

    # What the vault holds: type, URL or secret name, never the secret itself.
    try:
        vault_id = managed.vault_id()
        credentials = list(client.beta.vaults.credentials.list(vault_id))
    except Exception as error:
        findings.append(Finding(None, "credentials in the vault", _short(error)))
        credentials = []
    held: set[str] = set()
    for credential in credentials:
        auth = credential.auth
        kind = getattr(auth, "type", "?")
        url = getattr(auth, "mcp_server_url", None)
        key = url or getattr(auth, "secret_name", None) or "?"
        hosts = credential_hosts(auth)
        if hosts is not None:
            key = f"{key}  substituted only on: {', '.join(hosts) or '(no hosts)'}"
        expires = getattr(auth, "expires_at", None)
        suffix = f", token expires {expires}" if expires else ""
        rows.append(Row(f"vault: {credential.display_name}", f"{kind}  {key}{suffix}"))
        if kind == "mcp_oauth" and _is_past(expires):
            findings.append(
                Finding(
                    None,
                    f"'{credential.display_name}' access token is past its expiry",
                    f"it expired {expires}. A stored refresh token lets Anthropic renew it "
                    "when the Calendar is next used, so this alone is not a failure. If the "
                    "Calendar then reports an auth error, sign in again",
                    "`uv run concierge auth calendar`",
                    harmless=True,
                )
            )
        if url:
            held.add(normalize_url(url))
            if normalize_url(url) not in called:
                findings.append(
                    Finding(
                        None,
                        f"leftover vault credential '{credential.display_name}'",
                        f"stored for {url}, which no applied agent calls. It is ignored, so "
                        "it does not affect sessions (probably from an earlier address)",
                        "optional: `uv run concierge setup vault --remove-stale` deletes it",
                        harmless=True,
                    )
                )
    if credentials or called:
        for url, names in sorted(called.items()):
            if url in held:
                findings.append(Finding(True, f"the vault has a credential for {url}", "", ""))
            else:
                findings.append(
                    Finding(
                        False,
                        f"the vault has a credential for {url}",
                        f"used by {', '.join(sorted(set(names)))}; without it the call is "
                        "made with no credentials",
                        "run `uv run concierge setup vault`"
                        + (" and `uv run concierge auth calendar`" if "/calendar/" in url else ""),
                    )
                )

    findings += _credential_host_findings(client, managed, settings, credentials)
    findings += _deployment_remote_finding(client, managed, rows)

    if rows and all(f.ok is True or f.harmless for f in findings):  # nothing wrong, nothing skipped
        findings.append(Finding(True, "applied agents and vault credentials match .env"))
    return rows, findings


def credential_hosts(auth: Any) -> list[str] | None:
    """Hosts an environment_variable credential is substituted on; None if it is not one,
    or if it is unrestricted."""
    networking = getattr(auth, "networking", None)
    if getattr(auth, "type", None) != "environment_variable" or networking is None:
        return None
    if getattr(networking, "type", None) != "limited":
        return None
    return [str(h) for h in getattr(networking, "allowed_hosts", None) or []]


def environment_hosts(client: Any, managed: ManagedResources, settings: Settings) -> list[str]:
    """The hosts the environment's network policy allows: as applied if readable, else the file."""
    try:
        environment = client.beta.environments.retrieve(managed.environment_id())
        hosts = environment.config.networking.allowed_hosts
        if hosts is not None:
            return [str(h) for h in hosts]
    except Exception:  # not readable here: fall back to the file below
        pass
    path = settings.managed_dir / "environments" / f"{settings.environment}.yaml"
    match = ALLOWED_HOSTS.search(path.read_text(encoding="utf-8")) if path.exists() else None
    return [h.strip() for h in match.group(1).split(",") if h.strip()] if match else []


def _credential_host_findings(
    client: Any, managed: ManagedResources, settings: Settings, credentials: list[Any]
) -> list[Finding]:
    """Each secret may only be used on hosts the environment permits, and on ours."""
    findings: list[Finding] = []
    environment = None
    for credential in credentials:
        hosts = credential_hosts(credential.auth)
        if hosts is None:
            continue
        if environment is None:
            environment = environment_hosts(client, managed, settings)
        name = credential.display_name
        blocked = [h for h in hosts if h not in environment]
        if blocked:
            findings.append(
                Finding(
                    False,
                    f"credential '{name}' hosts are allowed by the environment",
                    f"it is substituted on {', '.join(hosts)}, but the environment only allows "
                    f"{', '.join(environment) or 'no hosts'}. Sessions start with an error "
                    f"for: {', '.join(blocked)}",
                    "run `uv run concierge setup vault` (it resets the hosts to your address)",
                )
            )
        elif settings.public_host not in hosts:
            findings.append(
                Finding(
                    False,
                    f"credential '{name}' covers your address",
                    f"it is substituted on {', '.join(hosts) or 'no hosts'}, not on "
                    f"{settings.public_host}, so calls to your server would carry only a "
                    "placeholder",
                    "run `uv run concierge setup vault`",
                )
            )
        else:
            findings.append(Finding(True, f"credential '{name}' hosts match the environment"))
    return findings


def _deployment_remote_finding(
    client: Any, managed: ManagedResources, rows: list[Row]
) -> list[Finding]:
    """What the *applied* deployment attaches (the file can differ until ``ant apply`` runs)."""
    try:
        deployment_id = managed.deployment_id()
        vault_id = managed.vault_id()
    except NotAppliedError:
        return []
    try:
        deployment = client.beta.deployments.retrieve(deployment_id)
    except Exception as error:
        return [Finding(None, "the applied deployment", _short(error))]
    attached = list(getattr(deployment, "vault_ids", None) or [])
    rows.append(Row("deployment daily-review: vaults", ", ".join(attached) or "(none)"))
    if vault_id in attached:
        return [Finding(True, APPLIED_LABEL)]
    return [
        Finding(
            False,
            APPLIED_LABEL,
            f"the deployment in your workspace attaches {attached or 'no vault'}; the vault "
            f"`setup vault` fills is {vault_id}. Sessions from `review run` and the schedule "
            "therefore have no credentials",
            "run `uv run concierge setup deployment`, then `ant apply` from inside managed/ "
            "(or `uv run concierge review run --direct`, which attaches the vault itself)",
        )
    ]


MCP_KINDS = {"mcp_authentication_failed_error", "mcp_connection_failed_error"}


def explain_issue(client: Any, settings: Settings, session_id: str, issue: Any) -> list[str]:
    """Plain-language account of one session error, chosen by its type."""
    if issue.kind == "credential_host_unreachable_error":
        return _explain_credential_hosts(client, settings, issue)
    if issue.kind in MCP_KINDS or "MCP server" in issue.message:
        return explain_session(client, settings, session_id)
    return []


def _explain_credential_hosts(client: Any, settings: Settings, issue: Any) -> list[str]:
    name = issue.credential_id or "a vault credential"
    hosts: list[str] | None = None
    if issue.vault_id and issue.credential_id:
        try:
            credential = client.beta.vaults.credentials.retrieve(
                issue.credential_id, vault_id=issue.vault_id
            )
            name = f"'{credential.display_name}' ({getattr(credential.auth, 'secret_name', '?')})"
            hosts = credential_hosts(credential.auth)
        except Exception as error:
            name = f"{name} ({_short(error)})"
    allowed = environment_hosts(client, ManagedResources(settings.managed_dir), settings)
    return [
        f"The vault credential {name} may be used on: "
        f"{', '.join(hosts) if hosts is not None else '(could not read its hosts)'}.",
        f"The environment's network policy allows: {', '.join(allowed) or '(no hosts)'}.",
        "A credential can only be used on hosts the environment allows; any extra host makes "
        "every new session report this error, and the secret is not usable.",
        "Fix: `uv run concierge setup vault` resets the credential's hosts to "
        f"{settings.public_host}. Then start a new session (existing ones keep the old "
        "settings). If the environment is the side that is wrong, run `uv run concierge setup "
        "host`, then `ant apply` from inside managed/.",
    ]


def explain_session(client: Any, settings: Settings, session_id: str) -> list[str]:
    """Plain-language account of why a session's MCP server found no credential.

    Compares what the session really had (attached vaults, the credentials inside them) with
    the addresses the agents call. Secrets are never read: the API does not return them.
    """
    managed = ManagedResources(settings.managed_dir)
    wanted = expected_urls(settings)
    try:
        session = client.beta.sessions.retrieve(session_id)
    except Exception as error:
        return [f"Could not read the session to explain the failure ({_short(error)})."]
    attached = list(getattr(session, "vault_ids", None) or [])
    lines = [f"The session attached these vaults: {', '.join(attached) or '(none)'}."]
    try:
        ours = managed.vault_id()
    except NotAppliedError:
        ours = None
    if not attached:
        lines += [
            "With no vault attached, no MCP server can receive a credential.",
            "If the session came from `review run` or the schedule, the deployment has no "
            "vault_ids. Fix: `uv run concierge setup deployment`, then `ant apply` from "
            "inside managed/. To run now without that: `uv run concierge review run --direct`.",
        ]
        return lines
    if ours and ours not in attached:
        lines.append(
            f"`setup vault` fills {ours}, which is not one of them, so the credentials you "
            "stored are in another vault. Fix: `uv run concierge setup deployment` and "
            "`ant apply` from inside managed/ (or check for a second vault applied from "
            "another folder)."
        )
    held: set[str] = set()
    for vault_id in attached:
        try:
            credentials = list(client.beta.vaults.credentials.list(vault_id))
        except Exception as error:
            lines.append(f"{vault_id}: could not list credentials ({_short(error)}).")
            continue
        urls = [str(getattr(c.auth, "mcp_server_url", "") or "") for c in credentials]
        urls = [u for u in urls if u]
        held |= {normalize_url(u) for u in urls}
        lines.append(f"{vault_id} holds credentials for: {', '.join(urls) or '(none)'}.")
    for name, url in wanted.items():
        if normalize_url(url) not in held:
            lines.append(
                f"No attached vault has a credential for the {name} address {url}. It must "
                "match exactly (https, same path). Fix: `uv run concierge setup vault`"
                + (" and `uv run concierge auth calendar`." if name == "calendar" else ".")
            )
    return lines


def _is_past(value: Any) -> bool:
    from datetime import UTC, datetime

    if value is None:
        return False
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment < datetime.now(UTC)


def _short(error: Exception) -> str:
    return f"could not check ({type(error).__name__}: {str(error)[:160]})"


def problems(findings: Iterable[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.ok is False]
