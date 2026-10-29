"""Tests for the package metadata."""

import tomllib
from pathlib import Path

import kb

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert kb.__version__ == project["version"]
