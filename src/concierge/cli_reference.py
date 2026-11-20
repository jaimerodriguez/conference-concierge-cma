"""Generate ``docs/CLI.md`` from the command line itself, so the reference cannot drift.

    uv run python -m concierge.cli_reference           # rewrite docs/CLI.md
    uv run python -m concierge.cli_reference --check   # exit 1 if the file is out of date

``tests/test_cli_reference.py`` runs the same comparison, and also fails when a command,
argument or option has no help text.
"""

from __future__ import annotations

import sys
from typing import Any

import typer

from concierge.config import REPO_ROOT

REFERENCE_PATH = REPO_ROOT / "docs" / "CLI.md"
_SKIP = {"help", "install_completion", "show_completion"}

INTRO = """\
# Command reference

Every `concierge` command and option. This file is generated from the code
(`uv run python -m concierge.cli_reference`) and a test fails if it is out of date, so it
always matches what the program accepts.

Ask the program itself at any level, for example:

```sh
uv run concierge --help
uv run concierge setup --help
uv run concierge setup vault --help
```

Run everything with `uv run` from the repo root (or from anywhere inside the repo).
Options with a default can be left out. `--install-completion` and `--show-completion`
(shell tab-completion) exist on the top-level command only.
"""


def _commands(group: Any, path: tuple[str, ...]) -> list[tuple[tuple[str, ...], Any]]:
    found: list[tuple[tuple[str, ...], Any]] = []
    for name, command in group.commands.items():
        if hasattr(command, "commands"):
            found += _commands(command, (*path, name))
        else:
            found.append(((*path, name), command))
    return found


def _params(command: Any) -> list[Any]:
    return [p for p in command.params if p.name not in _SKIP]


def all_commands() -> list[tuple[tuple[str, ...], Any]]:
    """(path, click command) for every leaf command, in the order they are declared."""
    from concierge.cli import app

    return _commands(typer.main.get_command(app), ("concierge",))


def missing_help() -> list[str]:
    """Commands, arguments and options that have no help text."""
    missing = []
    for path, command in all_commands():
        name = " ".join(path)
        if not (command.help or "").strip():
            missing.append(name)
        for param in _params(command):
            if not (getattr(param, "help", None) or "").strip():
                missing.append(f"{name} {param.name if _is_argument(param) else param.opts[0]}")
    return missing


def _default(param: Any) -> str:
    if param.default in (None, ""):
        return "none"
    if isinstance(param.default, bool):
        return "on" if param.default else "off"
    return f"`{param.default}`"


def _is_argument(param: Any) -> bool:
    return param.param_type_name == "argument"


def _usage(path: tuple[str, ...], command: Any) -> str:
    parts = list(path)
    for param in _params(command):
        if _is_argument(param):
            label = param.name.upper()
            parts.append(label if param.required else f"[{label}]")
    if any(not _is_argument(param) for param in _params(command)):
        parts.append("[OPTIONS]")
    return " ".join(parts)


def render() -> str:
    lines = [INTRO.rstrip(), ""]
    # Group by the first word after `concierge`, so setup/auth/review/agenda sit together.
    for path, command in all_commands():
        lines += [f"## `{' '.join(path)}`", "", (command.help or "").strip().split("\n\n")[0], ""]
        lines += [f"```sh\nuv run {_usage(path, command)}\n```", ""]
        params = _params(command)
        if params:
            lines += ["| Argument or option | Default | What it does |", "| --- | --- | --- |"]
            for param in params:
                if not _is_argument(param):
                    names = " / ".join([*param.opts, *param.secondary_opts])
                    default = _default(param)
                else:
                    names = param.name.upper() + ("" if param.required else " (optional)")
                    default = "required" if param.required else _default(param)
                lines.append(f"| `{names}` | {default} | {param.help} |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    text = render()
    if "--check" in sys.argv:
        current = REFERENCE_PATH.read_text(encoding="utf-8") if REFERENCE_PATH.exists() else ""
        if current != text:
            print("docs/CLI.md is out of date: run `uv run python -m concierge.cli_reference`")
            raise SystemExit(1)
        return
    REFERENCE_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {REFERENCE_PATH}")


if __name__ == "__main__":
    main()
