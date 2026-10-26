"""Tests for the run context: the content repository and the date."""

from datetime import date
from pathlib import Path

import pytest

from kb import context
from kb.errors import KbError


def test_load_takes_the_root_from_the_environment_and_the_date_from_kb_today(
    tmp_path: Path,
) -> None:
    environ = {"KB_CONTENT": str(tmp_path), "KB_TODAY": "2026-10-26"}
    loaded = context.load(environ, "linux", tmp_path / "home")
    assert loaded == context.Context(root=tmp_path.resolve(), today=date(2026, 10, 26))


def test_load_reads_the_root_from_the_config_file(tmp_path: Path) -> None:
    root = tmp_path / "notes"
    root.mkdir()
    config = tmp_path / "xdg" / "kb" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'content = "{root}"\n', encoding="utf-8")
    loaded = context.load({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}, "linux", tmp_path)
    assert loaded.root == root.resolve()


def test_load_without_any_root_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(KbError, match=r"^knowledge base: no content repository"):
        context.load({}, "linux", tmp_path)
