"""Fixtures for the end-to-end tests."""

from pathlib import Path

import pytest

from .harness import Kb, make_git_kb, make_kb


@pytest.fixture
def kb(tmp_path: Path) -> Kb:
    """A kb runner over a fresh copy of the content fixture."""
    return make_kb(tmp_path)


@pytest.fixture
def git_kb(tmp_path: Path) -> Kb:
    """A kb runner whose content repository is a git repository holding the fixture."""
    return make_git_kb(tmp_path)
