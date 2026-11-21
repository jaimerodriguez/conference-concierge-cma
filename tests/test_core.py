"""Tests for the pieces that need no network: content, lock-file lookup, and guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from concierge.abstracts import build_system_prompt
from concierge.catalog import load_catalog, rubric_for_track
from concierge.config import REPO_ROOT, Settings
from concierge.managed import ManagedResources, NotAppliedError
from concierge.moderation import MAX_TOPIC_CHARS, moderate_topic
from concierge.review import load_review_kickoff
from concierge.sessions import budget

CONTENT = REPO_ROOT / "content"
MANAGED = REPO_ROOT / "managed"


def test_every_track_has_a_rubric_and_every_event_a_venue() -> None:
    catalog = load_catalog(CONTENT)
    for track in catalog.tracks:
        rubric = rubric_for_track(CONTENT, track.id)
        assert "Base rubric" in rubric and "Track rubric" in rubric
    assert (CONTENT / "venues" / f"{catalog.event.venue}.md").exists()


def test_abstract_prompt_is_built_from_persona_and_track(settings: Settings) -> None:
    catalog = load_catalog(CONTENT)
    prompt = build_system_prompt(
        settings, catalog.persona("data-engineer"), catalog.track("lightning")
    )
    assert "Data engineer" in prompt and "Lightning talks" in prompt and "5 minutes" in prompt


def test_lock_file_lookup(tmp_path: Path) -> None:
    managed = ManagedResources(tmp_path)
    with pytest.raises(NotAppliedError):
        managed.agent_id("program-chair")
    lock = {"resources": {"./agents/program-chair/agent.md": {"id": "agent_123"}}}
    (tmp_path / "claude-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    assert managed.agent_id("program-chair") == "agent_123"
    with pytest.raises(NotAppliedError):
        managed.vault_id()


def test_moderation_rejects_empty_and_oversized_topics_without_a_model_call() -> None:
    no_client = None  # these checks must not reach the API
    assert moderate_topic(no_client, "   ").allowed is False  # type: ignore[arg-type]
    assert moderate_topic(no_client, "x" * (MAX_TOPIC_CHARS + 1)).allowed is False  # type: ignore[arg-type]


def test_budget_uses_minor_units_as_a_string() -> None:
    assert budget(50) == {"type": "limit", "max_list_cost": {"amount": "50", "currency": "USD"}}


def test_review_kickoff_is_a_single_outcome_with_a_rubric() -> None:
    events = load_review_kickoff(MANAGED)
    assert [event["type"] for event in events] == ["user.define_outcome"]
    assert events[0]["rubric"]["content"].strip()


def test_managed_agent_files_have_valid_frontmatter() -> None:
    agent_files = sorted((MANAGED / "agents").glob("*/agent.md"))
    assert len(agent_files) == 7
    for path in agent_files:
        _, frontmatter, body = path.read_text(encoding="utf-8").split("---\n", 2)
        config = yaml.safe_load(frontmatter)
        assert config["name"] == path.parent.name
        assert config["model"].startswith("claude-")
        assert body.strip()
        # Every MCP toolset must name a server the same file declares.
        servers = {server["name"] for server in config.get("mcp_servers", [])}
        toolsets = {t["mcp_server_name"] for t in config["tools"] if t["type"] == "mcp_toolset"}
        assert toolsets <= servers


def test_phase_2b_files_are_in_sync_with_managed(tmp_path: Path) -> None:
    """The committed phase 2b files must match what the generator produces today."""
    import importlib.util

    script = REPO_ROOT / "phase2" / "b-self-hosted-service" / "make_managed.py"
    spec = importlib.util.spec_from_file_location("make_managed", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.generate(tmp_path / "managed")
    committed = script.parent / "managed"
    fresh = {
        p.relative_to(tmp_path / "managed"): p.read_text()
        for p in (tmp_path / "managed").rglob("*")
        if p.is_file()
    }
    existing = {
        p.relative_to(committed): p.read_text() for p in committed.rglob("*") if p.is_file()
    }
    assert fresh == existing, "Run: uv run python phase2/b-self-hosted-service/make_managed.py"

    chair = existing[Path("agents/program-chair/agent.md")]
    assert "type: coordinator" in chair and "advisor" not in chair and "workflow" not in chair


def test_agent_lookup_stops_while_agent_files_name_the_sample_host(tmp_path: Path) -> None:
    from concierge.config import PLACEHOLDER_HOST
    from concierge.managed import PlaceholderHostError

    agent = tmp_path / "agents" / "chair" / "agent.md"
    agent.parent.mkdir(parents=True)
    agent.write_text(f"url: https://{PLACEHOLDER_HOST}/eventdb/mcp\n", encoding="utf-8")
    lock = {"resources": {"./agents/chair/agent.md": {"id": "agent_1"}}}
    (tmp_path / "claude-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    managed = ManagedResources(tmp_path)
    with pytest.raises(PlaceholderHostError, match="setup host"):
        managed.agent_id("chair")
    agent.write_text("url: https://abc.trycloudflare.com/eventdb/mcp\n", encoding="utf-8")
    assert managed.agent_id("chair") == "agent_1"


def _fake_ant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plan: str, code: int = 0) -> Path:
    """A stand-in `ant` that lists --dry-run in help and prints ``plan`` for the dry run."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "ant"
    script.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        '  [ "$a" = "--help" ] && echo "  --dry-run  print the plan" && exit 0\n'
        "done\n"
        f"echo '{plan}'\nexit {code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return tmp_path


def test_pending_changes_uses_the_ant_plan_not_file_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agents").mkdir()
    managed = ManagedResources(tmp_path)
    _fake_ant(tmp_path, monkeypatch, "Nothing to apply.")
    assert managed.pending_changes().state == "none"


def test_pending_changes_reports_a_plan_with_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agents").mkdir()
    _fake_ant(tmp_path, monkeypatch, "~ agents/chair/agent.md (update)")
    result = ManagedResources(tmp_path).pending_changes()
    assert result.state == "pending"
    assert "agent.md" in result.output


def test_pending_changes_unknown_when_ant_fails_or_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agents").mkdir()
    _fake_ant(tmp_path, monkeypatch, "not logged in", code=1)
    assert ManagedResources(tmp_path).pending_changes().state == "unknown"
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    assert ManagedResources(tmp_path).pending_changes().state == "unknown"


def test_settings_paths_do_not_depend_on_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concierge.config import REPO_ROOT, Settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONCIERGE_MANAGED_DIR", "phase2/b-self-hosted-service/managed")
    settings = Settings(_env_file=None)
    assert settings.db_path == REPO_ROOT / ".concierge" / "concierge.db"
    assert settings.state_path == REPO_ROOT / ".concierge" / "state.json"
    assert settings.managed_dir == REPO_ROOT / "phase2" / "b-self-hosted-service" / "managed"
    assert Settings.model_config["env_file"] == REPO_ROOT / ".env"


def test_doctor_says_the_same_from_any_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from concierge.cli import app
    from concierge.config import REPO_ROOT

    runner = CliRunner()
    monkeypatch.chdir(REPO_ROOT)
    from_root = runner.invoke(app, ["doctor"])
    monkeypatch.chdir(REPO_ROOT / "managed")
    from_managed = runner.invoke(app, ["doctor"])
    assert from_managed.output == from_root.output
    assert from_managed.exit_code == from_root.exit_code


# --- URL wiring: where the server address lives and whether it agrees -------------------


def _settings_for(tmp_path: Path, base_url: str, **extra: object) -> Settings:
    from concierge.config import Settings

    return Settings(
        _env_file=None,
        public_base_url=base_url,
        managed_dir=tmp_path / "managed",
        state_path=tmp_path / "state.json",
        **extra,
    )


def _agent_file(managed: Path, name: str, host: str) -> None:
    path = managed / "agents" / name / "agent.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'url: "https://{host}/eventdb/mcp"\n', encoding="utf-8")


def test_normalize_url_matches_the_way_the_vault_does() -> None:
    from concierge.wiring import normalize_url

    assert normalize_url("HTTPS://Coco.Example.com:443/eventdb/mcp/") == (
        "https://coco.example.com/eventdb/mcp"
    )
    assert normalize_url("http://coco.example.com/eventdb/mcp") != normalize_url(
        "https://coco.example.com/eventdb/mcp"
    )


def test_local_check_flags_http_state_and_file_mismatches(tmp_path: Path) -> None:
    from concierge.state import save_state
    from concierge.wiring import check_local, problems

    settings = _settings_for(tmp_path, "http://meetup.example.org")
    _agent_file(settings.managed_dir, "chair", "meetup.exmaple.org")
    save_state(settings.state_path, {"managed_host": "meetup.exmaple.org"})
    _, findings = check_local(settings, tmp_path / "none")
    labels = [f.label for f in problems(findings)]
    assert "the address in .env uses https" in labels
    assert "`setup host` used the host in .env" in labels
    assert "managed/ files use the host in .env" in labels

    good = _settings_for(tmp_path, "https://meetup.example.org")
    _agent_file(good.managed_dir, "chair", "meetup.example.org")
    save_state(good.state_path, {"managed_host": "meetup.example.org"})
    assert not problems(check_local(good, tmp_path / "none")[1])


class _FakeClient:
    """Just enough of the SDK's agents and vault calls for the remote checks."""

    def __init__(self, agent_urls: list[str], credentials: list[object]) -> None:
        from types import SimpleNamespace as NS

        agent = NS(version=3, mcp_servers=[NS(url=url) for url in agent_urls])
        self.beta = NS(
            agents=NS(retrieve=lambda _id: agent),
            vaults=NS(credentials=NS(list=lambda _vault: credentials)),
        )


def _credential(url: str | None, name: str = "Event DB", secret_name: str | None = None) -> object:
    from types import SimpleNamespace as NS

    return NS(
        display_name=name,
        auth=NS(type="static_bearer", mcp_server_url=url, secret_name=secret_name),
    )


def _applied(tmp_path: Path, base_url: str) -> Settings:
    settings = _settings_for(tmp_path, base_url)
    _agent_file(settings.managed_dir, "chair", "coco.example.com")
    lock = {
        "resources": {
            "./agents/chair/agent.md": {"id": "agent_1"},
            "./vaults/concierge.yaml": {"id": "vlt_1"},
        }
    }
    (settings.managed_dir / "claude-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    return settings


def test_remote_check_passes_when_agents_and_vault_agree(tmp_path: Path) -> None:
    from concierge.wiring import check_remote, problems

    settings = _applied(tmp_path, "https://coco.example.com")
    url = "https://coco.example.com/eventdb/mcp"
    rows, findings = check_remote(_FakeClient([url], [_credential(url + "/")]), settings)
    assert not problems(findings)
    assert any("agent chair (v3)" in row.place for row in rows)
    assert any("static_bearer" in row.value and url in row.value for row in rows)


def test_remote_check_explains_an_http_https_credential_mismatch(tmp_path: Path) -> None:
    from concierge.wiring import check_remote, problems

    settings = _applied(tmp_path, "https://coco.example.com")
    client = _FakeClient(
        ["https://coco.example.com/eventdb/mcp"],
        [_credential("http://coco.example.com/eventdb/mcp")],
    )
    findings = check_remote(client, settings)[1]
    labels = [f.label for f in problems(findings)]
    assert any("the vault has a credential for https://coco.example.com" in x for x in labels)
    assert not any("leftover" in label for label in labels)  # a leftover is a note, not a todo
    assert any(f.harmless and "leftover vault credential 'Event DB'" in f.label for f in findings)


def test_leftover_credential_does_not_block_a_clean_doctor(tmp_path: Path) -> None:
    from concierge.wiring import check_remote, problems

    settings = _applied(tmp_path, "https://coco.example.com")
    url = "https://coco.example.com/eventdb/mcp"
    old = _credential("https://old.trycloudflare.com/eventdb/mcp", name="Old")
    findings = check_remote(_FakeClient([url], [_credential(url), old]), settings)[1]
    assert not problems(findings)
    assert any(
        f.ok is True and f.label == f"the vault has a credential for {url}" for f in findings
    )
    assert any(f.harmless and "Old" in f.label for f in findings)


def test_find_stale_credentials_lists_only_unused_mcp_addresses(tmp_path: Path) -> None:
    from concierge.vaults import find_stale_credentials

    settings = _applied(tmp_path, "https://coco.example.com")
    current = _credential("https://coco.example.com/eventdb/mcp", name="Current")
    old = _credential("https://old.trycloudflare.com/eventdb/mcp", name="Old")
    secret = _credential(None, name="Key", secret_name="CLOUDCREDITS_API_KEY")
    stale = find_stale_credentials(_FakeClient([], [current, old, secret]), settings)
    assert [c.display_name for c in stale] == ["Old"]


def test_remote_check_flags_an_agent_applied_with_another_host(tmp_path: Path) -> None:
    from concierge.wiring import check_remote, problems

    settings = _applied(tmp_path, "https://coco.example.com")
    url = "https://old.example.com/eventdb/mcp"
    findings = check_remote(_FakeClient([url], [_credential(url)]), settings)[1]
    assert any(f.label == "agent chair calls the address in .env" for f in problems(findings))


def test_remote_check_reports_what_it_could_not_check(tmp_path: Path) -> None:
    from concierge.wiring import check_remote

    settings = _applied(tmp_path, "https://coco.example.com")
    client = _FakeClient([], [])

    def boom(_id: str) -> object:
        raise RuntimeError("no network")

    client.beta.agents.retrieve = boom  # type: ignore[attr-defined]
    findings = check_remote(client, settings)[1]
    assert any(f.ok is None and "no network" in f.detail for f in findings)


# --- the deployment path: `review run` and the schedule -----------------------------------


def _with_deployment(tmp_path: Path, base_url: str, vault_ids: str) -> Settings:
    settings = _applied(tmp_path, base_url)
    deployments = settings.managed_dir / "deployments"
    deployments.mkdir()
    (deployments / "daily-review.yaml").write_text(
        f"name: x\n# a comment\nvault_ids: {vault_ids}\nresources: []\n", encoding="utf-8"
    )
    lock_path = settings.managed_dir / "claude-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["resources"]["./deployments/daily-review.yaml"] = {"id": "depl_1"}
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return settings


def test_setup_deployment_writes_the_vault_id_and_keeps_the_rest(tmp_path: Path) -> None:
    settings = _with_deployment(tmp_path, "https://coco.example.com", "[]")
    managed = ManagedResources(settings.managed_dir)
    assert managed.set_deployment_vault() is True
    assert managed.deployment_vault_ids() == ["vlt_1"]
    text = (settings.managed_dir / "deployments" / "daily-review.yaml").read_text("utf-8")
    assert "# a comment" in text and "resources: []" in text
    assert managed.set_deployment_vault() is False  # already set: nothing to do


def test_doctor_flags_a_deployment_file_with_no_vault(tmp_path: Path) -> None:
    from concierge.wiring import check_local, problems

    settings = _with_deployment(tmp_path, "https://coco.example.com", "[]")
    labels = [f.label for f in problems(check_local(settings, tmp_path / "none")[1])]
    assert "the deployment file attaches the vault" in labels
    ManagedResources(settings.managed_dir).set_deployment_vault()
    assert not problems(check_local(settings, tmp_path / "none")[1])


def test_remote_check_flags_an_applied_deployment_without_the_vault(tmp_path: Path) -> None:
    from types import SimpleNamespace as NS

    from concierge.wiring import check_remote, problems

    settings = _with_deployment(tmp_path, "https://coco.example.com", "[vlt_1]")
    url = "https://coco.example.com/eventdb/mcp"
    client = _FakeClient([url], [_credential(url)])
    client.beta.deployments = NS(retrieve=lambda _id: NS(vault_ids=[]))
    findings = check_remote(client, settings)[1]
    assert "the applied deployment attaches the vault" in [f.label for f in problems(findings)]
    client.beta.deployments = NS(retrieve=lambda _id: NS(vault_ids=["vlt_1"]))
    assert not problems(check_remote(client, settings)[1])


def test_explain_session_names_the_missing_vault(tmp_path: Path) -> None:
    from types import SimpleNamespace as NS

    from concierge.wiring import explain_session

    settings = _with_deployment(tmp_path, "https://coco.example.com", "[]")
    client = _FakeClient([], [])
    client.beta.sessions = NS(retrieve=lambda _id: NS(vault_ids=[]))
    text = " ".join(explain_session(client, settings, "sesn_1"))
    assert "(none)" in text and "setup deployment" in text and "--direct" in text


def test_explain_session_compares_attached_vault_with_the_addresses(tmp_path: Path) -> None:
    from types import SimpleNamespace as NS

    from concierge.wiring import explain_session

    settings = _with_deployment(tmp_path, "https://coco.example.com", "[vlt_1]")
    old = _credential("https://old.trycloudflare.com/eventdb/mcp")
    client = _FakeClient([], [old])
    client.beta.sessions = NS(retrieve=lambda _id: NS(vault_ids=["vlt_1"]))
    text = " ".join(explain_session(client, settings, "sesn_1"))
    assert "old.trycloudflare.com" in text
    assert "https://coco.example.com/eventdb/mcp" in text and "setup vault" in text


def test_deployment_problem_is_reported_once_and_expired_oauth_is_only_a_note(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace as NS

    from concierge.wiring import check_local, check_remote, merge_deployment_findings, problems

    settings = _with_deployment(tmp_path, "https://coco.example.com", "[]")
    url = "https://coco.example.com/eventdb/mcp"
    client = _FakeClient([url], [_credential(url)])
    client.beta.deployments = NS(retrieve=lambda _id: NS(vault_ids=[]))
    findings = check_local(settings, tmp_path / "none")[1] + check_remote(client, settings)[1]
    assert len(problems(merge_deployment_findings(findings))) == 1

    oauth = _credential(url, name="Calendar")
    oauth.auth.type = "mcp_oauth"
    oauth.auth.expires_at = "2020-01-01T00:00:00+00:00"
    notes = check_remote(_FakeClient([url], [oauth]), settings)[1]
    assert not problems(notes)
    assert any(f.harmless and "past its expiry" in f.label for f in notes)


# --- secrets that may only be used on some hosts ------------------------------------------


def _secret_credential(hosts: list[str]) -> object:
    from types import SimpleNamespace as NS

    return NS(
        id="vcrd_1",
        display_name="CloudCredits sponsor API key",
        auth=NS(
            type="environment_variable",
            secret_name="CLOUDCREDITS_API_KEY",
            networking=NS(type="limited", allowed_hosts=hosts),
        ),
    )


def _env_file(settings: Settings, hosts: str) -> None:
    folder = settings.managed_dir / "environments"
    folder.mkdir(exist_ok=True)
    (folder / f"{settings.environment}.yaml").write_text(
        f"config:\n  networking:\n    allowed_hosts: [{hosts}]\n", encoding="utf-8"
    )


def test_doctor_shows_credential_hosts_and_flags_one_the_environment_forbids(
    tmp_path: Path,
) -> None:
    from concierge.wiring import check_remote, problems

    settings = _applied(tmp_path, "https://coco.example.com")
    _env_file(settings, "coco.example.com")
    url = "https://coco.example.com/eventdb/mcp"
    stale = _secret_credential(["old.trycloudflare.com"])
    rows, findings = check_remote(_FakeClient([url], [_credential(url), stale]), settings)
    assert any("old.trycloudflare.com" in row.value for row in rows)
    labels = [f.label for f in problems(findings)]
    assert (
        "credential 'CloudCredits sponsor API key' hosts are allowed by the environment" in labels
    )
    good = _secret_credential(["coco.example.com"])
    findings = check_remote(_FakeClient([url], [_credential(url), good]), settings)[1]
    assert not problems(findings)


def test_setup_vault_rotation_resets_the_credential_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace as NS

    from concierge import vaults

    settings = _settings_for(tmp_path, "https://coco.example.com")
    sent: dict[str, object] = {}
    existing = _secret_credential(["old.trycloudflare.com"])
    client = NS(
        beta=NS(
            vaults=NS(
                credentials=NS(
                    list=lambda _v: [existing],
                    update=lambda _id, vault_id, auth: sent.update(auth),
                )
            )
        )
    )
    vaults.store_cloudcredits_key(client, "vlt_1", settings)
    assert sent["networking"] == {"type": "limited", "allowed_hosts": ["coco.example.com"]}


def test_a_host_error_is_explained_as_a_host_problem_not_an_mcp_problem(tmp_path: Path) -> None:
    from types import SimpleNamespace as NS

    from concierge.sessions import SessionIssue
    from concierge.wiring import explain_issue

    settings = _applied(tmp_path, "https://coco.example.com")
    _env_file(settings, "coco.example.com")
    stale = _secret_credential(["old.trycloudflare.com"])
    client = _FakeClient([], [])
    client.beta.vaults.credentials.retrieve = lambda _id, vault_id: stale  # type: ignore[attr-defined]
    event = NS(
        error=NS(
            type="credential_host_unreachable_error",
            message="credential is configured for hosts that the policy does not permit",
            credential_id="vcrd_1",
            vault_id="vlt_1",
        )
    )
    issue = SessionIssue.from_event(event)
    text = " ".join(explain_issue(client, settings, "sesn_1", issue))
    assert "old.trycloudflare.com" in text and "setup vault" in text
    assert "MCP" not in text and "attached these vaults" not in text


def test_agenda_budget_leaves_room_for_breaks_and_buffer() -> None:
    from concierge.agenda import talk_budget

    event = load_catalog(CONTENT).event  # 18:30-21:00, 10-minute breaks, 10-minute buffer
    assert talk_budget(event) == {
        "window_minutes": 150,
        "breaks": 2,
        "break_minutes": 20,
        "buffer_minutes": 10,
        "talk_minutes_available": 120,
    }


def test_agenda_fit_counts_what_is_already_accepted() -> None:
    from concierge.agenda import check_fit

    event = load_catalog(CONTENT).event

    def proposal(n: int, fmt: str) -> dict[str, str]:
        return {"id": f"p{n}", "title": f"Talk {n}", "format": fmt}

    # The run that overran: 3 talks and 5 lightning talks already accepted (100 minutes).
    accepted = [proposal(n, "talk") for n in range(3)]
    accepted += [proposal(n, "lightning") for n in range(3, 8)]
    candidates = [proposal(8, "talk"), proposal(9, "talk"), proposal(10, "lightning")]
    candidates += [proposal(11, "lightning"), accepted[0]]

    result = check_fit(event, accepted, candidates)

    assert result["accepted_minutes"] == 100 and not result["already_overrun"]
    # Neither talk fits in the 20 minutes left, but both lightning talks do.
    assert [p["id"] for p in result["does_not_fit"]] == ["p8", "p9"]
    assert [p["id"] for p in result["fits"]] == ["p10", "p11"]
    assert result["minutes_left_after_fits"] == 10


def test_agenda_fit_reports_an_existing_overrun() -> None:
    from concierge.agenda import check_fit

    event = load_catalog(CONTENT).event
    accepted = [{"id": f"p{n}", "title": "T", "format": "talk"} for n in range(5)]

    result = check_fit(event, accepted, [])

    assert result["already_overrun"] and result["minutes_left_after_fits"] == -5
