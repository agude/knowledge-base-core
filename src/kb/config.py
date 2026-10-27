"""Where the content repository is: KB_CONTENT, else the config file's content key.

This module is the one place that reads the config file. Writing it belongs
to the setup command, which is not part of this release.
"""

import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

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
    if not config.is_file():
        return None
    try:
        text = config.read_text(encoding="utf-8")
    except OSError as error:
        raise KbError(
            f"knowledge base: cannot read config file {config}: {error.strerror}"
        ) from error
    return parse_content_setting(text, config)


def read_harvest_since(config: Path) -> datetime | None:
    """The optional harvest cutoff from the config file, normalized to UTC."""
    if not config.is_file():
        return None
    try:
        text = config.read_text(encoding="utf-8")
    except OSError as error:
        raise KbError(
            f"knowledge base: cannot read config file {config}: {error.strerror}"
        ) from error
    return parse_harvest_since(text, config)


def parse_content_setting(text: str, config: Path) -> Path | None:
    """The content key in config text, with ~ expanded, or None when it is absent."""
    try:
        data = tomllib.loads(text)
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
        data = tomllib.loads(text)
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
    return value.astimezone(UTC)


def _expand(text: str) -> Path:
    """A path with a leading ~ replaced by the home directory."""
    return Path(text).expanduser()
