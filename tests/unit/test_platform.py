"""Tests for the config file location and the scheduler query on each platform."""

from pathlib import Path

import pytest

from kb import platform

HOME = Path("/home/tester")


def test_xdg_config_home_wins_on_every_platform() -> None:
    environ = {"XDG_CONFIG_HOME": "/xdg", "LOCALAPPDATA": "C:/local"}
    assert platform.config_file(environ, platform.WINDOWS, HOME) == Path("/xdg/kb/config.toml")
    assert platform.config_file(environ, "linux", HOME) == Path("/xdg/kb/config.toml")


@pytest.mark.parametrize("name", ["linux", "darwin"])
def test_posix_systems_use_dot_config(name: str) -> None:
    assert platform.config_file({}, name, HOME) == HOME / ".config" / "kb" / "config.toml"


def test_an_empty_xdg_config_home_is_unset() -> None:
    assert platform.config_file({"XDG_CONFIG_HOME": ""}, "linux", HOME) == (
        HOME / ".config" / "kb" / "config.toml"
    )


def test_windows_uses_localappdata() -> None:
    environ = {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"}
    expected = Path(r"C:\Users\tester\AppData\Local") / "kb" / "config.toml"
    assert platform.config_file(environ, platform.WINDOWS, HOME) == expected


def test_windows_without_localappdata_falls_back_under_home() -> None:
    assert platform.config_file({}, platform.WINDOWS, HOME) == (
        HOME / "AppData" / "Local" / "kb" / "config.toml"
    )


def test_linux_asks_systemd_about_the_timer() -> None:
    commands = platform.scheduler_commands(platform.LINUX)
    assert commands == (
        ("systemctl", "--user", "is-enabled", "kb-sync.timer"),
        ("systemctl", "--user", "is-active", "kb-sync.timer"),
    )


def test_windows_asks_task_scheduler_for_the_task_state() -> None:
    commands = platform.scheduler_commands(platform.WINDOWS)
    assert commands is not None
    ((program, *arguments),) = commands
    assert program == "powershell.exe"
    assert arguments[-1] == "(Get-ScheduledTask -TaskName 'kb-sync' -ErrorAction Stop).State"


def test_other_platforms_have_no_scheduler_query() -> None:
    assert platform.scheduler_commands("darwin") is None
