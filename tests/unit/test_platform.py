"""Tests for the config file location on each platform."""

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
