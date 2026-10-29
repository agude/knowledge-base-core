"""Classify managed skills before setup replaces or leaves them."""

import sys
from pathlib import Path

import pytest

from kb import skills
from kb.errors import KbError

FILES = {"SKILL.md": b"---\nname: curate\n---\n"}
SKIP_LINKS = pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privilege")


def managed(path: Path, files: dict[str, bytes] = FILES) -> None:
    """Write a managed test skill with its supplied files."""
    path.mkdir(parents=True)
    (path / skills.MARKER).write_text("0.1.0\n", encoding="utf-8")
    for relative, data in files.items():
        destination = path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def test_an_absent_skill_is_installed(tmp_path: Path) -> None:
    assert skills.classify(tmp_path / "skills" / "curate", FILES, tmp_path / "Knowledge") == (
        skills.SkillAction.INSTALL
    )


def test_a_managed_skill_with_matching_files_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "curate"
    managed(path)

    assert skills.classify(path, FILES, tmp_path / "Knowledge") == skills.SkillAction.UNCHANGED


def test_a_managed_skill_with_different_files_is_updated(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "curate"
    managed(path, {"SKILL.md": b"old\n"})

    assert skills.classify(path, FILES, tmp_path / "Knowledge") == skills.SkillAction.UPDATE


def test_a_managed_skill_with_an_extra_file_is_updated(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "curate"
    managed(path)
    (path / "notes.txt").write_text("extra\n", encoding="utf-8")

    assert skills.classify(path, FILES, tmp_path / "Knowledge") == skills.SkillAction.UPDATE


@SKIP_LINKS
@pytest.mark.parametrize("replace_old", [False, True])
def test_a_link_into_old_tooling_uses_the_replace_flag(tmp_path: Path, replace_old: bool) -> None:
    old_root = tmp_path / "Knowledge"
    target = old_root / "skills" / "curate"
    target.mkdir(parents=True)
    path = tmp_path / "skills" / "curate"
    path.parent.mkdir(parents=True)
    path.symlink_to(target)

    action = skills.classify(path, FILES, old_root, replace_old=replace_old)

    assert action == (
        skills.SkillAction.REPLACE_OLD_LINK if replace_old else skills.SkillAction.REFUSE_OLD_LINK
    )


@SKIP_LINKS
def test_a_link_outside_old_tooling_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "other" / "curate"
    target.mkdir(parents=True)
    path = tmp_path / "skills" / "curate"
    path.parent.mkdir(parents=True)
    path.symlink_to(target)

    assert skills.classify(path, FILES, tmp_path / "Knowledge") == (
        skills.SkillAction.REFUSE_FOREIGN
    )


def test_a_foreign_directory_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "curate"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_bytes(FILES["SKILL.md"])

    assert skills.classify(path, FILES, tmp_path / "Knowledge") == (
        skills.SkillAction.REFUSE_FOREIGN
    )


def test_a_foreign_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "curate"
    path.parent.mkdir(parents=True)
    path.write_text("mine\n", encoding="utf-8")

    assert skills.classify(path, FILES, tmp_path / "Knowledge") == (
        skills.SkillAction.REFUSE_FOREIGN
    )


def test_package_files_rejects_unknown_skills() -> None:
    with pytest.raises(KbError, match="unknown skill: unknown"):
        skills.package_files("unknown")


def test_install_creates_leaves_and_updates_a_managed_skill(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "curate"
    old_root = tmp_path / "Knowledge"

    assert skills.install(path, FILES, "1.2.3", old_root) == "installed"
    assert (path / skills.MARKER).read_text(encoding="utf-8") == "1.2.3\n"
    assert (path / "SKILL.md").read_bytes() == FILES["SKILL.md"]
    assert skills.install(path, FILES, "1.2.3", old_root) == "unchanged"

    updated_files = {"SKILL.md": b"updated\n"}
    assert skills.install(path, updated_files, "1.2.4", old_root) == "updated"
    assert (path / skills.MARKER).read_text(encoding="utf-8") == "1.2.4\n"
    assert (path / "SKILL.md").read_bytes() == updated_files["SKILL.md"]


@SKIP_LINKS
def test_install_replaces_only_the_old_tooling_link(tmp_path: Path) -> None:
    old_root = tmp_path / "Knowledge"
    target = old_root / "skills" / "curate"
    target.mkdir(parents=True)
    target_file = target / "SKILL.md"
    target_file.write_bytes(b"old tooling bytes\n")
    path = tmp_path / "skills" / "curate"
    path.parent.mkdir(parents=True)
    path.symlink_to(target)

    assert skills.install(path, FILES, "1.2.3", old_root, replace_old=True) == "updated"
    assert path.is_dir() and not path.is_symlink()
    assert target_file.read_bytes() == b"old tooling bytes\n"


def test_failed_update_restores_the_previous_managed_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "skills" / "curate"
    managed(path, {"SKILL.md": b"original\n"})
    original_replace = Path.replace
    fail_temporary_install = True

    def replace_once(source: Path, target: Path) -> Path:
        nonlocal fail_temporary_install
        if fail_temporary_install and source.name.endswith(".tmp"):
            fail_temporary_install = False
            raise OSError("injected directory rename failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", replace_once)
    with pytest.raises(OSError, match="injected directory rename failure"):
        skills.install(path, FILES, "1.2.3", tmp_path / "Knowledge")

    assert (path / "SKILL.md").read_bytes() == b"original\n"
    assert (path / skills.MARKER).read_text(encoding="utf-8") == "0.1.0\n"
    assert sorted(path.parent.iterdir()) == [path]


@SKIP_LINKS
def test_a_managed_directory_with_a_nested_link_is_updated(tmp_path: Path) -> None:
    path = tmp_path / "skills" / "curate"
    managed(path)
    target = tmp_path / "external.txt"
    target.write_text("external\n", encoding="utf-8")
    (path / "external.txt").symlink_to(target)

    assert skills.classify(path, FILES, tmp_path / "Knowledge") == skills.SkillAction.UPDATE
