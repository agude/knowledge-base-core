"""Read and atomically edit the machine config file."""

import os
import shutil
import tomllib
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from kb import corpus, dates, toml_edit
from kb.errors import KbError

NO_CONTENT = (
    'knowledge base: no content repository; set KB_CONTENT or add content = "PATH" to {config}'
)


def content_root(environ: Mapping[str, str], config: Path) -> Path:
    """The content repository as an absolute, resolved path.

    KB_CONTENT wins when it is set and not empty. Otherwise the config file's
    content key is used. Raises KbError when neither gives a directory.
    """
    override = environ.get("KB_CONTENT", "")
    if override:
        root = _expand(override)
    else:
        configured = read_content_setting(config)
        if configured is None:
            raise KbError(NO_CONTENT.format(config=config))
        root = configured
    resolved = root.resolve()
    if not resolved.is_dir():
        raise KbError(f"knowledge base: content root is not a directory: {root}")
    return resolved


def read_content_setting(config: Path) -> Path | None:
    """The content key in the config file, or None when the file or key is absent."""
    text = _read_text(config)
    if text is None:
        return None
    return parse_content_setting(text, config)


def read_harvest_since(config: Path) -> datetime | None:
    """The optional harvest cutoff from the config file, normalized to UTC."""
    text = _read_text(config)
    if text is None:
        return None
    return parse_harvest_since(text, config)


def parse_content_setting(text: str, config: Path) -> Path | None:
    """The content key in config text, with ~ expanded, or None when it is absent."""
    try:
        data = tomllib.loads(corpus.strip_bom(text))
    except tomllib.TOMLDecodeError as error:
        raise KbError(f"knowledge base: invalid config file {config}: {error}") from error
    value = data.get("content")
    if value is None:
        return None
    if not isinstance(value, str):
        raise KbError(f"knowledge base: invalid config file {config}: content must be a string")
    if not value:
        raise KbError(f"knowledge base: invalid config file {config}: content must not be empty")
    return _expand(value)


def parse_harvest_since(text: str, config: Path) -> datetime | None:
    """Parse an optional timezone-aware TOML datetime used as the transcript cutoff."""
    try:
        data = tomllib.loads(corpus.strip_bom(text))
    except tomllib.TOMLDecodeError as error:
        raise KbError(f"knowledge base: invalid config file {config}: {error}") from error
    value = data.get("harvest_since")
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise KbError(
            f"knowledge base: invalid config file {config}: "
            "harvest_since must be a time-zone-aware TOML datetime"
        )
    utc = dates.to_utc(value)
    if utc is None:
        raise KbError(
            f"knowledge base: invalid config file {config}: "
            "harvest_since must normalize to a representable UTC timestamp"
        )
    return utc


def set_harvest_since(text: str, moment: datetime, config: Path) -> str:
    """Set the top-level transcript cutoff, preserving all other config text.

    An existing valid cutoff is left byte-for-byte unchanged. A nested cutoff or an invalid
    top-level value is refused because neither has the meaning the harvester reads.
    """
    try:
        before = tomllib.loads(corpus.strip_bom(text))
    except tomllib.TOMLDecodeError as error:
        raise KbError(f"knowledge base: invalid config file {config}: {error}") from error
    if _has_nested_harvest_since(before):
        raise KbError(
            f"knowledge base: invalid config file {config}: harvest_since must be a top-level key"
        )
    if before.get("harvest_since") is not None:
        parse_harvest_since(text, config)
        return text
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise KbError("harvest_since requires a time-zone-aware current time")
    utc = dates.to_utc(moment)
    if utc is None:
        raise KbError("harvest_since requires a representable UTC current time")
    cutoff = utc.replace(microsecond=0)
    stamp = cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")
    lines = text.splitlines(keepends=True)
    result = toml_edit.insert_line(
        text, lines, toml_edit.first_table_line(lines), f"harvest_since = {stamp}"
    )
    try:
        after = tomllib.loads(corpus.strip_bom(result))
    except tomllib.TOMLDecodeError as error:
        raise KbError(f"knowledge base: invalid config file {config}: {error}") from error
    if after.get("harvest_since") != cutoff:
        raise KbError("harvest_since did not take the new value")
    if _without_harvest_since(before) != _without_harvest_since(after):
        raise KbError("the edit would change keys other than harvest_since")
    return result


def write_config(config: Path, edit: Callable[[str], str]) -> tuple[str, str]:
    """Apply an edit through a sibling temporary file and atomically replace the config.

    A symbolic link is followed, so the link itself survives and its target is replaced.
    Returns the file state and edited text.
    """
    target = config.resolve() if config.is_symlink() else config
    existed = target.exists()
    old = target.read_bytes().decode("utf-8") if existed else ""
    new = edit(old)
    if existed and new == old:
        return "unchanged", new
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{os.urandom(4).hex()}.tmp"
    try:
        temporary.write_bytes(new.encode("utf-8"))
        if existed:
            shutil.copymode(target, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return ("updated" if existed else "created"), new


def _read_text(config: Path) -> str | None:
    """The config file's UTF-8 text, or None when it is not a file."""
    if not config.is_file():
        return None
    try:
        return config.read_text(encoding="utf-8")
    except OSError as error:
        raise KbError(
            f"knowledge base: cannot read config file {config}: {error.strerror}"
        ) from error


def _has_nested_harvest_since(data: dict[str, object]) -> bool:
    """Whether a non-top-level table contains a key named harvest_since."""

    def nested(value: object) -> bool:
        if isinstance(value, dict):
            return any(key == "harvest_since" or nested(item) for key, item in value.items())
        if isinstance(value, list):
            return any(nested(item) for item in value)
        return False

    return any(nested(value) for key, value in data.items() if key != "harvest_since")


def _without_harvest_since(data: dict[str, object]) -> dict[str, object]:
    """Top-level config keys except the cutoff."""
    return {key: value for key, value in data.items() if key != "harvest_since"}


def _expand(text: str) -> Path:
    """A path with a leading ~ replaced by the home directory."""
    return Path(text).expanduser()
