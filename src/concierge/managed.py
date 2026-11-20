"""Look up the IDs that ``ant apply`` recorded in ``managed/claude-lock.json``.

The CLI owns the control plane (agents, environments, stores, vaults, deployments are files
under ``managed/``). This code owns the data plane: it starts sessions with the stored IDs.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from concierge.config import PLACEHOLDER_HOST

LOCK_FILE = "claude-lock.json"


class NotAppliedError(RuntimeError):
    """A resource file exists but ``ant apply`` has not recorded an ID for it yet."""


class PlaceholderHostError(RuntimeError):
    """The agent files still point at the sample host, so the cloud could not reach the services."""


# The exact wording of ``ant``'s "no changes" plan has not been checked against every version,
# so accept the phrases it is known or likely to use. Anything else is shown to the person.
_NOTHING_TO_APPLY = re.compile(r"nothing to apply|no changes|up[- ]to[- ]date", re.IGNORECASE)


_VAULT_IDS_LINE = re.compile(r"^vault_ids:\s*\[([^\]]*)\]", re.MULTILINE)


@dataclass(frozen=True)
class PlanCheck:
    """Result of ``ant apply --dry-run``: ``none``, ``pending`` or ``unknown`` (could not tell)."""

    state: str
    output: str


@dataclass(frozen=True)
class ManagedResources:
    """Read-only view of ``claude-lock.json``."""

    managed_dir: Path

    def _resources(self) -> dict[str, dict[str, object]]:
        lock_path = self.managed_dir / LOCK_FILE
        if not lock_path.exists():
            raise NotAppliedError(
                f"{lock_path} not found. Run `ant apply` from {self.managed_dir} first "
                "(see docs/guides/01-declaring-agents-with-ant-cli.md)."
            )
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        return data.get("resources", {})

    def files_with_placeholder_host(self) -> list[Path]:
        """Agent and environment files that still name the sample host."""
        candidates = [
            path
            for folder in ("agents", "environments")
            for path in sorted((self.managed_dir / folder).rglob("*"))
            if path.suffix in {".md", ".yaml"} and path.is_file()
        ]
        return [p for p in candidates if PLACEHOLDER_HOST in p.read_text(encoding="utf-8")]

    def apply(self, folders: list[str], *, yes: bool = False) -> int:
        """Run ``ant apply`` from inside ``managed/`` and return its exit code.

        Output and prompts go straight to the terminal: unless ``yes`` is set, ``ant`` shows
        its plan and asks before it changes anything. Never run from the repo root, where
        ``ant apply`` would also pick up the phase 2 files.
        """
        ant = shutil.which("ant")
        if ant is None:
            raise RuntimeError(
                "The `ant` CLI is not on PATH. See README, 'Install the prerequisites'."
            )
        command = [ant, "apply", *(["--yes"] if yes else []), *folders]
        return subprocess.run(command, cwd=self.managed_dir, check=False).returncode

    def pending_changes(self, timeout: float = 90.0) -> PlanCheck:
        """Ask ``ant apply --dry-run`` what it would change. Never applies anything.

        File times say nothing about whether a file differs from what the cloud holds (a rewrite
        with identical content touches the file but changes nothing), so the CLI's own plan is the
        source of truth. We only run the flag if this ``ant`` lists it in ``apply --help``.
        """
        ant = shutil.which("ant")
        if ant is None:
            return PlanCheck("unknown", "the `ant` CLI is not on PATH")
        folders = [
            name
            for name in ("agents", "environments", "memory_stores", "vaults")
            if (self.managed_dir / name).is_dir()
        ]

        def run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [ant, *args],
                cwd=self.managed_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                check=False,
            )

        try:
            if "--dry-run" not in (help_ := run("apply", "--help")).stdout + help_.stderr:
                return PlanCheck("unknown", "this `ant` version has no `apply --dry-run`")
            result = run("apply", "--dry-run", *folders)
        except (OSError, subprocess.TimeoutExpired) as error:
            return PlanCheck("unknown", f"could not run `ant apply --dry-run` ({error})")
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return PlanCheck("unknown", output or f"ant exited with code {result.returncode}")
        if _NOTHING_TO_APPLY.search(output):
            return PlanCheck("none", output)
        return PlanCheck("pending", output)

    def check_host(self) -> None:
        """Stop early, with the fix, when the agents would call a host that is not yours."""
        files = self.files_with_placeholder_host()
        if files:
            names = ", ".join(str(path.relative_to(self.managed_dir)) for path in files[:3])
            raise PlaceholderHostError(
                f"The agent files still point at the sample host {PLACEHOLDER_HOST} "
                f"({names}{', ...' if len(files) > 3 else ''}). The cloud sandbox and MCP proxy "
                "reach your mock services through your tunnel address, so run "
                "`uv run concierge setup host` (it reads CONCIERGE_PUBLIC_BASE_URL from .env), "
                "then `ant apply` again from inside the managed/ folder (not the repo root). "
                "See README, 'Your tunnel address'."
            )

    def resource_id(self, relative_path: str) -> str:
        """Return the ID for a file such as ``agents/program-chair/agent.md``.

        # Guide 01 · Declaring an agent and applying it with the CLI · Step 4: read the ID back
        Lock-file keys are the file's path as the plan printed it (``./agents/...``), so match
        on the normalized path rather than on an exact string.
        """
        wanted = Path(relative_path).as_posix().removeprefix("./")
        for key, entry in self._resources().items():
            if Path(key).as_posix().removeprefix("./") == wanted:
                return str(entry["id"])
        raise NotAppliedError(
            f"No ID recorded for {relative_path}. Run `ant apply {relative_path}` "
            f"from {self.managed_dir}."
        )

    def agent_id(self, name: str) -> str:
        self.check_host()
        return self.resource_id(f"agents/{name}/agent.md")

    def environment_id(self, name: str | None = None) -> str:
        """The environment sessions run in. See ``Settings.environment`` for how it is chosen."""
        from concierge.config import get_settings

        settings = get_settings()
        if name is None and settings.environment_id:
            return settings.environment_id
        return self.resource_id(f"environments/{name or settings.environment}.yaml")

    def memory_store_id(self, name: str) -> str:
        return self.resource_id(f"memory_stores/{name}.yaml")

    def vault_id(self, name: str = "concierge") -> str:
        return self.resource_id(f"vaults/{name}.yaml")

    def deployment_id(self, name: str = "daily-review") -> str:
        return self.resource_id(f"deployments/{name}.yaml")

    def deployment_vault_ids(self, name: str = "daily-review") -> list[str]:
        """The ``vault_ids`` written in the deployment file (IDs, not paths)."""
        text = (self.managed_dir / "deployments" / f"{name}.yaml").read_text(encoding="utf-8")
        match = _VAULT_IDS_LINE.search(text)
        return [item.strip() for item in match.group(1).split(",") if item.strip()] if match else []

    def set_deployment_vault(self, name: str = "daily-review") -> bool:
        """Write the applied vault's ID into the deployment file. True when the file changed.

        # Guide 10 · Scheduling an agent · Step 2: a deployment takes vault IDs, not paths
        Without it a fired session has no vault, so its MCP servers get no credentials.
        """
        path = self.managed_dir / "deployments" / f"{name}.yaml"
        wanted = [self.vault_id()]
        if self.deployment_vault_ids(name) == wanted:
            return False
        text = path.read_text(encoding="utf-8")
        line = f"vault_ids: [{', '.join(wanted)}]"
        if not _VAULT_IDS_LINE.search(text):
            raise RuntimeError(f"No `vault_ids: [...]` line found in {path}")
        path.write_text(_VAULT_IDS_LINE.sub(line, text, count=1), encoding="utf-8")
        return True
