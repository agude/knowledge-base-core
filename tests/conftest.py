"""Isolate every test from the user's real configuration and content repository."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_user(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point HOME and XDG_CONFIG_HOME at an empty directory and unset KB_CONTENT.

    A test that forgets to set up its own content repository then fails with "no content
    repository" instead of reading or writing the user's knowledge base through
    ~/.config/kb/config.toml.
    """
    home: Path = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "localappdata"))
    monkeypatch.delenv("KB_CONTENT", raising=False)
