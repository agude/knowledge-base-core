"""Locating the content repository and reading shared settings."""

from __future__ import annotations

import os
from pathlib import Path

# The repository root: the directory holding kb/ and pyproject.toml.
ROOT = Path(__file__).resolve().parent.parent

INT_MAX = 2**63 - 1


class UsageError(Exception):
    """A bad argument or setting; the message is printed as is, exit 1."""


def content_dir() -> Path:
    """KB_CONTENT_DIR, or <root>/content when it is unset or empty."""
    configured = os.environ.get("KB_CONTENT_DIR")
    return Path(configured) if configured else ROOT / "content"


def nonnegative(option: str, value: str) -> int:
    """Parse a decimal count the way every option and setting does."""
    if not value.isascii() or not value.isdigit():
        raise UsageError(f"Error: {option} takes a non-negative number")
    number = int(value)
    if number > INT_MAX:
        raise UsageError(f"Error: {option} exceeds the supported integer range")
    return number


def yaml_escape(text: str) -> str:
    """Escape a value for a double-quoted YAML scalar, as the bash writers do."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
