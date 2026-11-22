"""`concierge setup public` puts the sample values back so the resource files can be published."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from concierge import cli
from concierge.config import PLACEHOLDER_HOST, Settings
from concierge.publish import find_private_values, private_hosts, restore_placeholders

HOST = "coco.mine.test"
VAULT = "vlt_011ChC2LxHZj2GNyyrcoQGZM"


def _tree(root: Path) -> Path:
    managed = root / "managed"
    (managed / "agents" / "chair").mkdir(parents=True)
    (managed / "environments").mkdir()
    (managed / "deployments").mkdir()
    (managed / "agents" / "chair" / "agent.md").write_text(
        f'---\nmcp_servers:\n  - {{url: "https://{HOST}/eventdb/mcp"}}\n---\nBody.\n', "utf-8"
    )
    (managed / "environments" / "cloud.yaml").write_text(
        f"allowed_hosts: [{HOST.upper()}]\n", "utf-8"
    )
    (managed / "deployments" / "daily-review.yaml").write_text(
        f"# paste its vlt_... ID here\nvault_ids: [{VAULT}]\nresources: []\n", "utf-8"
    )
    (managed / "claude-lock.json").write_text(json.dumps({"host": HOST}), "utf-8")
    return managed


def test_private_hosts_drops_the_placeholder_and_blanks() -> None:
    assert private_hosts(HOST, PLACEHOLDER_HOST, "", None, HOST.upper()) == [HOST]


def test_finds_the_host_and_the_vault_id(tmp_path: Path) -> None:
    managed = _tree(tmp_path)
    found = {(f.path.name, f.value) for f in find_private_values([managed], [HOST])}
    assert found == {("agent.md", HOST), ("cloud.yaml", HOST), ("daily-review.yaml", VAULT)}


def test_restore_puts_the_placeholders_back_and_keeps_the_rest(tmp_path: Path) -> None:
    managed = _tree(tmp_path)
    changed = restore_placeholders([managed], [HOST])
    assert len(changed) == 3
    assert find_private_values([managed], [HOST]) == []
    agent = (managed / "agents" / "chair" / "agent.md").read_text("utf-8")
    assert f"https://{PLACEHOLDER_HOST}/eventdb/mcp" in agent and "Body." in agent
    deployment = (managed / "deployments" / "daily-review.yaml").read_text("utf-8")
    assert "vault_ids: []" in deployment and "paste its vlt_... ID" in deployment
    # The lock file is git-ignored and belongs to `ant apply`: leave it alone.
    assert HOST in (managed / "claude-lock.json").read_text("utf-8")
    assert restore_placeholders([managed], [HOST]) == []  # already clean


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(
        _env_file=None,
        public_base_url=f"https://{HOST}",
        managed_dir=_tree(tmp_path),
        state_path=tmp_path / "state.json",
    )
    settings.state_path.write_text(json.dumps({"managed_host": HOST}), "utf-8")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    return settings


def test_check_lists_the_values_and_changes_nothing(repo: Settings) -> None:
    before = (repo.managed_dir / "environments" / "cloud.yaml").read_text("utf-8")
    result = CliRunner().invoke(cli.app, ["setup", "public", "--check"])
    assert result.exit_code == 1
    assert HOST in result.output and VAULT in result.output
    assert (repo.managed_dir / "environments" / "cloud.yaml").read_text("utf-8") == before


def test_public_then_host_round_trips(repo: Settings) -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["setup", "public"])
    assert result.exit_code == 0, result.output
    assert runner.invoke(cli.app, ["setup", "public", "--check"]).exit_code == 0
    assert json.loads(repo.state_path.read_text("utf-8"))["managed_host"] == PLACEHOLDER_HOST

    result = runner.invoke(cli.app, ["setup", "host"])
    assert result.exit_code == 0, result.output
    agent = (repo.managed_dir / "agents" / "chair" / "agent.md").read_text("utf-8")
    assert f"https://{HOST}/eventdb/mcp" in agent
