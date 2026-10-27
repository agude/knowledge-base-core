"""Isolate every test from the user's real configuration and content repository."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_user(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point user and transcript settings at empty temporary locations.

    A test that forgets to set up its own content repository then fails with "no content
    repository" instead of reading or writing the user's knowledge base. Transcript parser
    tests must opt into fixtures explicitly, and time-dependent tests must set KB_NOW.
    """
    home: Path = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "localappdata"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.delenv("KB_CONTENT", raising=False)
    monkeypatch.delenv("KB_NOW", raising=False)
