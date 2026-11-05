"""Tests for the config file and Goose session locations, and the scheduler query, per platform."""

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


@pytest.mark.parametrize("name", ["linux", "darwin", platform.WINDOWS])
def test_an_absolute_goose_path_root_holds_the_sessions_on_every_platform(name: str) -> None:
    root = "C:/goose" if name == platform.WINDOWS else "/goose"
    environ = {"GOOSE_PATH_ROOT": root, "XDG_DATA_HOME": "/xdg-data", "APPDATA": "C:/roaming"}
    assert platform.goose_sessions(environ, name, HOME) == Path(root) / "data" / "sessions"


@pytest.mark.parametrize("name", ["linux", "darwin"])
def test_posix_goose_sessions_follow_xdg_data_home_or_dot_local_share(name: str) -> None:
    assert platform.goose_sessions({"XDG_DATA_HOME": "/xdg-data"}, name, HOME) == Path(
        "/xdg-data/goose/sessions"
    )
    assert platform.goose_sessions({}, name, HOME) == HOME / ".local" / "share" / "goose" / (
        "sessions"
    )


def test_goose_ignores_a_relative_path_root_or_data_home() -> None:
    environ = {"GOOSE_PATH_ROOT": "relative", "XDG_DATA_HOME": "data"}
    assert platform.goose_sessions(environ, "linux", HOME) == (
        HOME / ".local" / "share" / "goose" / "sessions"
    )
    assert platform.goose_sessions({"GOOSE_PATH_ROOT": "/goose"}, platform.WINDOWS, HOME) == (
        HOME / "AppData" / "Roaming" / "Block" / "goose" / "data" / "sessions"
    )


def test_windows_goose_sessions_are_under_appdata() -> None:
    environ = {"APPDATA": r"C:\Users\tester\AppData\Roaming", "XDG_DATA_HOME": "/xdg-data"}
    expected = Path(r"C:\Users\tester\AppData\Roaming") / "Block" / "goose" / "data"
    assert platform.goose_sessions(environ, platform.WINDOWS, HOME) == expected / "sessions"


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
