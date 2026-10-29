"""Package and install kb-managed skills for the supported agent hosts."""

import os
import shutil
import tempfile
from collections.abc import Mapping
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Literal

from kb.errors import KbError

SKILL_NAMES = ("knowledge-base", "curate")
MARKER = ".kb-managed"
SkillState = Literal["installed", "updated", "unchanged"]


class SkillAction(Enum):
    """The installer's action for one existing skill path."""

    INSTALL = "install"
    UNCHANGED = "unchanged"
    UPDATE = "update"
    REFUSE_FOREIGN = "refuse-foreign"


def package_files(name: str) -> dict[str, bytes]:
    """Read one skill's package files by relative path."""
    if name not in SKILL_NAMES:
        raise KbError(f"unknown skill: {name}")
    resource = resources.files("kb").joinpath("data", "skills", name, "SKILL.md")
    return {"SKILL.md": resource.read_bytes()}


def classify(path: Path, wanted: Mapping[str, bytes]) -> SkillAction:
    """Classify one host skill path without changing it."""
    if path.is_symlink():
        return SkillAction.REFUSE_FOREIGN
    if not path.exists():
        return SkillAction.INSTALL
    if not path.is_dir():
        return SkillAction.REFUSE_FOREIGN
    marker = path / MARKER
    if marker.is_symlink() or not marker.is_file():
        return SkillAction.REFUSE_FOREIGN
    return SkillAction.UNCHANGED if _skill_files(path) == dict(wanted) else SkillAction.UPDATE


def install(path: Path, wanted: Mapping[str, bytes], version: str) -> SkillState:
    """Install a package skill with a sibling directory rename, preserving foreign targets."""
    action = classify(path, wanted)
    if action is SkillAction.UNCHANGED:
        return "unchanged"
    if action is SkillAction.REFUSE_FOREIGN:
        raise KbError(
            f"{path} exists and kb did not install it; it is unchanged. "
            "Move it aside, then run setup again."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent))
    backup = _backup_path(path)
    old_moved = False
    new_installed = False
    try:
        for relative, data in wanted.items():
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (temporary / MARKER).write_text(f"{version}\n", encoding="utf-8")
        if action is SkillAction.UPDATE:
            path.replace(backup)
            old_moved = True
        temporary.replace(path)
        new_installed = True
    except BaseException:
        if old_moved:
            if new_installed:
                _remove(path)
            backup.replace(path)
        raise
    finally:
        _remove(temporary)
    if old_moved:
        _remove(backup)
    return "installed" if action is SkillAction.INSTALL else "updated"


def _skill_files(path: Path) -> dict[str, bytes] | None:
    """Files in a managed skill except its marker; None when a nested link or special file exists."""
    found: dict[str, bytes] = {}
    for entry in sorted(path.rglob("*")):
        relative = entry.relative_to(path).as_posix()
        if relative == MARKER:
            continue
        if entry.is_symlink():
            return None
        if entry.is_file():
            found[relative] = entry.read_bytes()
        elif not entry.is_dir():
            return None
    return found


def _remove(path: Path) -> None:
    """Remove a staged skill directory or a symbolic link without following it."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _backup_path(path: Path) -> Path:
    """An unused sibling path for the managed directory being replaced."""
    while True:
        candidate = path.with_name(f".{path.name}.{os.urandom(4).hex()}.old")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
