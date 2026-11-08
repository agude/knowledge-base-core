"""Typed views of article, question, and observation metadata, with the line each came from."""

from dataclasses import dataclass
from typing import Generic, TypeVar

from kb import model
from kb.model import Document, Section

T = TypeVar("T")


@dataclass(frozen=True)
class Located(Generic[T]):
    """A value and the one-based line it was read from."""

    value: T
    line: int


def resolve(document: Document, section: Section | None, name: str) -> Located[str] | None:
    """The section's own value, then its H2 parent's, then the article's front matter."""
    resolved = model.resolve_field(document, section, name)
    if resolved is None:
        return None
    value, line = resolved
    return Located(value, line if line is not None else 1)
