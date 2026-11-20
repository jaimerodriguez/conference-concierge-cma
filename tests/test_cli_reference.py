"""The command reference is generated from the CLI; keep it fresh and fully documented."""

from concierge.cli_reference import REFERENCE_PATH, missing_help, render


def test_every_command_argument_and_option_has_help() -> None:
    assert missing_help() == []


def test_command_reference_is_up_to_date() -> None:
    assert REFERENCE_PATH.read_text(encoding="utf-8") == render(), (
        "docs/CLI.md is out of date: run `uv run python -m concierge.cli_reference`"
    )
