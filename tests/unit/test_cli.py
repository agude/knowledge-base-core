"""Tests for dispatch, the global options, and usage errors in cli.py."""

import sys
from collections.abc import Callable, Sequence

import pytest

from kb import __version__, cli, registry
from kb.errors import KbError
from kb.registry import Command


def fake_command(name: str, run: Callable[[Sequence[str]], int]) -> tuple[Command, ...]:
    """One registered command whose run is the given callable."""
    return (Command(name=name, summary="Fake command.", run=run),)


def test_no_arguments_prints_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Usage: kb COMMAND [ARGS...]\n")
    assert out.endswith("Run `kb COMMAND --help` for one command's options.\n")


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_flags_print_the_help(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([flag]) == 0
    assert capsys.readouterr().out.startswith("Usage: kb COMMAND")


def test_version_flag_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out == f"kb {__version__}\n"


def test_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["nosuch"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Unknown command: nosuch\n"


def test_unknown_option_before_the_command_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--bogus", "recall"]) == 1
    assert capsys.readouterr().err == "Unknown option: --bogus\n"


def test_registered_command_receives_the_remaining_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def run(args: Sequence[str]) -> int:
        seen.append(list(args))
        return 7

    monkeypatch.setattr(registry, "COMMANDS", fake_command("fake", run))
    assert cli.main(["fake", "alpha", "--beta"]) == 7
    assert seen == [["alpha", "--beta"]]


def test_help_without_registered_commands_has_no_command_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(registry, "COMMANDS", ())
    assert cli.main([]) == 0
    assert "Commands:" not in capsys.readouterr().out


def test_registered_commands_are_listed_in_the_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(registry, "COMMANDS", fake_command("fake", lambda args: 0))
    assert cli.main([]) == 0
    assert "Commands:\n  fake  Fake command.\n" in capsys.readouterr().out


def test_usage_error_from_a_command_exits_with_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(args: Sequence[str]) -> int:
        raise KbError("Unknown option: --x")

    monkeypatch.setattr(registry, "COMMANDS", fake_command("fake", run))
    assert cli.main(["fake", "--x"]) == 1
    assert capsys.readouterr().err == "Unknown option: --x\n"


def test_main_reads_sys_argv_when_no_argv_is_given(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["kb", "--version"])
    assert cli.main() == 0
    assert capsys.readouterr().out == f"kb {__version__}\n"
