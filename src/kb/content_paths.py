"""Validation for fixed writable directories under the content root."""

from pathlib import Path

from kb.errors import KbError


def fixed_directory(
    root: Path,
    relative: str,
    *,
    command: str,
    create: bool,
    optional: bool = False,
) -> Path | None:
    """Resolve a fixed content directory without following directory symlinks."""
    components = relative.split("/")
    if any(component in ("", ".", "..") for component in components):
        raise KbError(f"{command}: unsafe content directory: {relative}")

    root_resolved = root.resolve()
    paths = [root.joinpath(*components[: index + 1]) for index in range(len(components))]
    missing = False
    for path in paths:
        if path.is_symlink():
            raise KbError(f"{command}: content directory is a symlink: {relative}")
        if not path.exists():
            missing = True
            continue
        if missing or not path.is_dir() or not path.resolve().is_relative_to(root_resolved):
            raise KbError(f"{command}: unsafe content directory: {relative}")

    if missing and not create:
        if optional:
            return None
        raise KbError(f"{command}: content directory is missing: {relative}")

    if create:
        for path in paths:
            if not path.exists():
                path.mkdir()
            if path.is_symlink():
                raise KbError(f"{command}: content directory is a symlink: {relative}")
            if not path.is_dir() or not path.resolve().is_relative_to(root_resolved):
                raise KbError(f"{command}: unsafe content directory: {relative}")

    return paths[-1]
