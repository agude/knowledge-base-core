"""End-to-end tests for the entry point and the usage errors it owns."""

import tomllib
from pathlib import Path

import pytest

from .harness import Kb

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_help_flag_prints_usage(kb: Kb) -> None:
    result = kb("--help")
    assert result.returncode == 0
    assert result.stdout.startswith("Usage: kb")
    assert result.stderr == ""


def test_no_arguments_prints_usage(kb: Kb) -> None:
    result = kb()
    assert result.returncode == 0
    assert result.stdout.startswith("Usage: kb")


@pytest.mark.xfail(strict=True, reason="recall, read, and map are not registered yet")
def test_help_lists_the_agent_commands(kb: Kb) -> None:
    lines = kb("--help").stdout.splitlines()
    for command in ("recall", "read", "map"):
        assert any(line.split()[:1] == [command] for line in lines)


def test_version_flag_prints_the_package_version(kb: Kb) -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    result = kb("--version")
    assert result.returncode == 0
    assert result.stdout == f"kb {project['version']}\n"


def test_unknown_command_is_a_usage_error(kb: Kb) -> None:
    result = kb("nosuch")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Unknown command: nosuch\n"


def test_unknown_option_before_the_command_is_a_usage_error(kb: Kb) -> None:
    result = kb("--bogus")
    assert result.returncode == 1
    assert result.stderr == "Unknown option: --bogus\n"
