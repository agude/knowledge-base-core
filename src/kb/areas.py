"""Normalize and compare contexts under the curated knowledge areas."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from kb import corpus
from kb.errors import KbError

AREAS = ("knowledge", "sources")
_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class _Resolution:
    """The resolved content path, or whether a path reaches outside the repository."""

    path: str | None
    external: bool = False


def for_storage(root: Path, value: str, who: str) -> str:
    """Normalize a supplied context and keep it content-relative when it resolves safely."""
    normalized = _normalize(value, who)
    resolution = _resolve_existing(root, normalized, who)
    if resolution.external:
        return _literal_area(normalized)
    if resolution.path is None:
        return _literal_area(normalized)
    if not is_area_path(resolution.path):
        raise KbError(f"{who}: context must be under knowledge/ or sources/")
    return resolution.path


def canonical_area(root: Path, value: str | None) -> str | None:
    """Resolve a stored context for comparison; unsafe or ambiguous values do not match."""
    if value is None:
        return None
    try:
        normalized = _normalize(value, "context")
        resolution = _resolve_existing(root, normalized, "context")
    except (KbError, OSError):
        return None
    if resolution.external:
        return None
    if resolution.path is not None:
        return resolution.path if is_area_path(resolution.path) else None
    literal = _literal_area(normalized)
    return literal if is_area_path(literal) else None


def is_area_path(path: str) -> bool:
    """Whether a content-relative path is knowledge/ or sources/, on component boundaries."""
    return any(path == area or path.startswith(area + "/") for area in AREAS)


def overlaps(first: str, second: str) -> bool:
    """Whether either normalized area path is the same as or an ancestor of the other."""
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def _normalize(value: str, who: str) -> str:
    """Validate relative path text, normalize separators, and collapse dot components."""
    if not value or not value.strip():
        raise KbError(f"{who}: context must not be blank")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise KbError(f"{who}: context must not contain control characters")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE.match(normalized):
        raise KbError(f"{who}: context must be a relative path")
    if "#" in normalized:
        raise KbError(f"{who}: context must not contain a fragment")
    components = normalized.split("/")
    if ".." in components:
        raise KbError(f"{who}: context must not contain .. components")
    path = "/".join(component for component in components if component not in ("", "."))
    if not path:
        raise KbError(f"{who}: context must not be blank")
    return path


def _resolve_existing(root: Path, normalized: str, who: str) -> _Resolution:
    """Resolve content-relative, knowledge-relative, and unique filename forms."""
    for candidate in (normalized, f"knowledge/{normalized}"):
        target = root / candidate
        try:
            resolved = target.resolve(strict=False)
        except (OSError, RuntimeError):
            return _Resolution(None, external=True)
        if not resolved.is_relative_to(root):
            return _Resolution(None, external=True)
        if target.exists():
            return _Resolution(resolved.relative_to(root).as_posix())

    if "/" in normalized:
        return _Resolution(None)
    try:
        path = corpus.resolve_path(root, normalized, who)
    except KbError as error:
        if "resolves outside the content repository" in str(error):
            return _Resolution(None, external=True)
        raise
    return _Resolution(path)


def _literal_area(normalized: str) -> str:
    """Keep an explicit knowledge/sources path, or treat a shorthand as knowledge-relative."""
    if is_area_path(normalized):
        return normalized
    return f"knowledge/{normalized}"
