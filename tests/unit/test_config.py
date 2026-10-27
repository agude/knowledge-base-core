"""Tests for finding the content repository."""

from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

import pytest

from kb import config
from kb.errors import KbError


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_kb_content_wins_over_the_config_file(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir()
    other = (tmp_path / "other").as_posix()
    config_path = write(tmp_path / "config.toml", f'content = "{other}"\n')
    assert config.content_root({"KB_CONTENT": str(root)}, config_path) == root.resolve()


def test_an_empty_kb_content_is_unset(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir()
    config_path = write(tmp_path / "config.toml", f'content = "{root.as_posix()}"\n')
    assert config.content_root({"KB_CONTENT": ""}, config_path) == root.resolve()


def test_the_config_file_supplies_the_root(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    root.mkdir()
    config_path = write(tmp_path / "config.toml", f'content = "{root.as_posix()}"\n')
    assert config.content_root({}, config_path) == root.resolve()


def test_no_setting_anywhere_names_the_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    with pytest.raises(KbError) as error:
        config.content_root({}, config_path)
    assert str(error.value) == (
        'knowledge base: no content repository; set KB_CONTENT or add content = "PATH" '
        f"to {config_path}"
    )


def test_a_kb_content_that_is_not_a_directory_is_reported(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(KbError, match=r"^knowledge base: content root is not a directory: "):
        config.content_root({"KB_CONTENT": str(missing)}, tmp_path / "config.toml")


def test_tilde_expands_in_kb_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "notes").mkdir()
    assert config.content_root({"KB_CONTENT": "~/notes"}, tmp_path / "x.toml") == (
        (tmp_path / "notes").resolve()
    )


def test_tilde_expands_in_the_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "notes").mkdir()
    config_path = write(tmp_path / "config.toml", 'content = "~/notes"\n')
    assert config.content_root({}, config_path) == (tmp_path / "notes").resolve()


def test_an_unreadable_config_file_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = write(tmp_path / "config.toml", 'content = "x"\n')

    def deny(self: Path, *args: object, **kwargs: object) -> str:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(KbError) as error:
        config.read_content_setting(config_path)
    assert str(error.value) == (
        f"knowledge base: cannot read config file {config_path}: Permission denied"
    )


def test_a_missing_config_file_has_no_setting(tmp_path: Path) -> None:
    assert config.read_content_setting(tmp_path / "config.toml") is None


def test_harvest_since_is_optional_and_normalized_to_utc(tmp_path: Path) -> None:
    path = write(tmp_path / "config.toml", "harvest_since = 2026-10-26T05:00:00-07:00\n")
    assert config.read_harvest_since(path) == datetime(2026, 10, 26, 12, tzinfo=UTC)
    assert config.read_harvest_since(tmp_path / "missing.toml") is None
    assert config.parse_harvest_since("content = '/repo'\n", path) is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("harvest_since = 2026-10-26\n", "harvest_since must be a time-zone-aware TOML datetime"),
        ("harvest_since = 12\n", "harvest_since must be a time-zone-aware TOML datetime"),
        (
            'harvest_since = "2026-10-26T12:00:00Z"\n',
            "harvest_since must be a time-zone-aware TOML datetime",
        ),
        (
            "harvest_since = 2026-10-26T12:00:00\n",
            "harvest_since must be a time-zone-aware TOML datetime",
        ),
        ("harvest_since = \n", "invalid config file"),
    ],
)
def test_invalid_harvest_since_is_reported(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(KbError, match=message):
        config.parse_harvest_since(text, tmp_path / "config.toml")


def test_unreadable_harvest_config_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = write(tmp_path / "config.toml", "harvest_since = 2026-10-26T12:00:00Z\n")

    def deny(self: Path, *args: object, **kwargs: object) -> str:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(KbError, match=r"^knowledge base: cannot read config file "):
        config.read_harvest_since(path)


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    with pytest.raises(KbError, match=r"^knowledge base: invalid config file "):
        config.parse_content_setting("content = \n", config_path)


def test_native_windows_path_is_normalized_before_toml_interpolation(tmp_path: Path) -> None:
    windows_path = PureWindowsPath(r"C:\Users\tester\Knowledge")
    config_path = tmp_path / "config.toml"

    with pytest.raises(KbError, match="invalid config file"):
        config.parse_content_setting(f'content = "{windows_path}"\n', config_path)

    normalized_path = windows_path.as_posix()
    assert config.parse_content_setting(f'content = "{normalized_path}"\n', config_path) == Path(
        normalized_path
    )


def test_a_config_without_a_content_key_has_no_setting(tmp_path: Path) -> None:
    assert config.parse_content_setting("other = 1\n", tmp_path / "config.toml") is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("content = 3\n", "content must be a string"),
        ('content = ""\n', "content must not be empty"),
    ],
)
def test_a_bad_content_value_is_reported(tmp_path: Path, text: str, message: str) -> None:
    config_path = tmp_path / "config.toml"
    with pytest.raises(KbError) as error:
        config.parse_content_setting(text, config_path)
    assert str(error.value) == f"knowledge base: invalid config file {config_path}: {message}"
