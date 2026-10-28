"""kb setup --print: option handling and the content path that the instruction block needs."""

from pathlib import Path

import pytest

from kb.commands import setup
from kb.errors import KbError


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty directory and clear the content override."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("KB_CONTENT", raising=False)
    return tmp_path


def test_help_prints_the_usage_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert setup.run(["--help"]) == 0
    assert capsys.readouterr().out.startswith("Usage: kb setup [--content PATH]")


@pytest.mark.parametrize("words", [["extra"], ["--print", "instructions", "extra"]])
def test_an_extra_word_is_a_usage_error(words: list[str]) -> None:
    with pytest.raises(KbError, match="Usage: kb setup"):
        setup.run(words)


def test_an_option_without_its_value_is_refused() -> None:
    with pytest.raises(KbError, match="requires an argument"):
        setup.run(["--print"])


def test_an_unknown_item_names_the_choices() -> None:
    with pytest.raises(KbError, match="takes instructions, allow-claude, allow-codex; not bogus"):
        setup.run(["--print", "bogus"])


def test_the_allow_items_need_no_content_path(
    isolated: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert setup.run(["--print", "allow-codex"]) == 0
    assert capsys.readouterr().out.startswith("# kb working-agent commands.")
    assert setup.run(["--print", "allow-claude"]) == 0
    assert '"Bash(kb recall *)"' in capsys.readouterr().out


def test_instructions_use_the_environment_content_path_without_requiring_it_to_exist(
    isolated: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    content = isolated / "not-yet-made"
    monkeypatch.setenv("KB_CONTENT", str(content))

    assert setup.run(["--print", "instructions"]) == 0

    assert f"Content policy: @{content}/AGENTS.md" in capsys.readouterr().out
    assert not content.exists()


def test_instructions_use_the_configured_content_path(
    isolated: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = isolated / "xdg" / "kb" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f'content = "{isolated / "configured"}"\n', encoding="utf-8")

    assert setup.run(["--print", "instructions"]) == 0

    assert f"@{isolated / 'configured'}/AGENTS.md" in capsys.readouterr().out


def test_instructions_without_any_content_path_are_refused(isolated: Path) -> None:
    with pytest.raises(KbError, match="no content path"):
        setup.run(["--print", "instructions"])
