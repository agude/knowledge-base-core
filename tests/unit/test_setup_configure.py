"""kb setup in process: the kb executable, the config write, the hook states, and the apply step."""

import shutil
import stat
import sys
from pathlib import Path

import pytest

from kb import setup_rules
from kb.commands import setup
from kb.errors import KbError

SHIM = '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "kb 0.1.0"; fi\n'
SKIP_LINKS = pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privilege")


def fake_kb(directory: Path, name: str = "kb", body: str = SHIM) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.skipif(sys.platform == "win32", reason="the test runs a POSIX shell script as kb")
def test_a_given_kb_must_print_its_version(tmp_path: Path) -> None:
    path = fake_kb(tmp_path, body="#!/bin/sh\necho hello\n")

    with pytest.raises(KbError, match="not a kb executable"):
        setup._kb_path(str(path))


def test_a_given_kb_that_does_not_run_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "kb"
    path.write_text("not a program\n", encoding="utf-8")

    with pytest.raises(KbError, match="does not run"):
        setup._kb_path(str(path))


def test_a_kb_path_with_a_single_quote_is_refused_before_it_runs(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="single quote"):
        setup._kb_path(str(tmp_path / "it's" / "kb"))


@SKIP_LINKS
def test_the_kb_path_is_absolute_without_resolving_a_symbolic_link(tmp_path: Path) -> None:
    real = fake_kb(tmp_path, name="real-kb")
    link = tmp_path / "link-kb"
    link.symlink_to(real)

    assert setup._kb_path(str(link)) == str(link.absolute())


@pytest.mark.skipif(sys.platform == "win32", reason="the test runs a POSIX shell script as kb")
def test_without_a_given_kb_the_path_comes_from_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = fake_kb(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: str(real))

    assert setup._kb_path(None) == str(real.absolute())


def test_without_a_given_kb_and_no_kb_on_path_the_setup_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(KbError, match="not on PATH"):
        setup._kb_path(None)


def test_the_config_is_created_with_its_directory(tmp_path: Path) -> None:
    config = tmp_path / "xdg" / "kb" / "config.toml"

    assert setup._write_config(config, "/c") == "created"
    assert config.read_text(encoding="utf-8") == 'content = "/c"\n'


def test_an_unchanged_config_is_not_rewritten(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('content = "/c"\n', encoding="utf-8")
    modified = config.stat().st_mtime_ns

    assert setup._write_config(config, "/c") == "unchanged"
    assert config.stat().st_mtime_ns == modified


def test_an_updated_config_keeps_its_mode_and_its_other_lines(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('content = "/old"\nharvest_since = 2026-10-24T00:00:00Z\n', encoding="utf-8")
    config.chmod(0o600)

    assert setup._write_config(config, "/new") == "updated"

    assert config.read_text(encoding="utf-8") == (
        'content = "/new"\nharvest_since = 2026-10-24T00:00:00Z\n'
    )
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


@SKIP_LINKS
def test_a_config_symbolic_link_is_followed_and_the_link_survives(tmp_path: Path) -> None:
    target = tmp_path / "dotfiles" / "config.toml"
    target.parent.mkdir()
    target.write_text("", encoding="utf-8")
    link = tmp_path / "config.toml"
    link.symlink_to(target)

    assert setup._write_config(link, "/c") == "updated"

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == 'content = "/c"\n'


def test_a_config_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_bytes(b"\xff\xfe")

    with pytest.raises(UnicodeError):
        setup._write_config(config, "/c")


@SKIP_LINKS
def test_each_kind_at_the_hook_path_is_classified(tmp_path: Path) -> None:
    directory = tmp_path / "hooks"
    directory.mkdir()
    absent = directory / "absent"
    file = directory / "file"
    file.write_bytes(b"x\n")
    link = directory / "link"
    link.symlink_to(tmp_path / "elsewhere")
    subdirectory = directory / "dir"
    subdirectory.mkdir()

    assert setup.existing_hook(absent) == setup_rules.ExistingHook("absent")
    assert setup.existing_hook(file) == setup_rules.ExistingHook("file", data=b"x\n")
    assert setup.existing_hook(link) == setup_rules.ExistingHook(
        "link", link_target=str(tmp_path / "elsewhere")
    )
    assert setup.existing_hook(subdirectory) == setup_rules.ExistingHook("other")


def test_applying_an_install_writes_the_script_executable_through_kb_tmp(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    hook = git / "hooks" / "pre-commit"
    script = setup_rules.hook_script("/opt/kb")

    assert setup._apply(setup_rules.HookAction.INSTALL, hook, script, git) == "installed"

    assert hook.read_text(encoding="utf-8") == script
    assert stat.S_IMODE(hook.stat().st_mode) & 0o111
    assert list((git / "kb-tmp").iterdir()) == []


def test_applying_an_unchanged_or_updated_hook(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    hook = git / "hooks" / "pre-commit"
    script = setup_rules.hook_script("/opt/kb")

    assert setup._apply(setup_rules.HookAction.UNCHANGED, hook, script, git) == "unchanged"
    assert not hook.exists()

    hook.parent.mkdir()
    hook.write_text("old\n", encoding="utf-8")
    assert setup._apply(setup_rules.HookAction.UPDATE, hook, script, git) == "updated"
    assert hook.read_text(encoding="utf-8") == script


@SKIP_LINKS
def test_replacing_an_old_link_leaves_its_target_unchanged(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "hooks").mkdir()
    old = tmp_path / "Knowledge" / "scripts" / "hooks" / "pre-commit"
    old.parent.mkdir(parents=True)
    old.write_text("old tooling\n", encoding="utf-8")
    hook = git / "hooks" / "pre-commit"
    hook.symlink_to(old)
    script = setup_rules.hook_script("/opt/kb")

    assert setup._apply(setup_rules.HookAction.REPLACE_OLD_LINK, hook, script, git) == "updated"

    assert not hook.is_symlink()
    assert hook.read_text(encoding="utf-8") == script
    assert old.read_text(encoding="utf-8") == "old tooling\n"


def test_the_refusals_name_the_flag_or_the_foreign_path(tmp_path: Path) -> None:
    hook = tmp_path / "pre-commit"
    script = setup_rules.hook_script("/opt/kb")

    with pytest.raises(KbError, match="--replace-old-hook"):
        setup._apply(setup_rules.HookAction.REFUSE_OLD_LINK, hook, script, tmp_path)
    with pytest.raises(KbError, match="did not install it"):
        setup._apply(setup_rules.HookAction.REFUSE_FOREIGN, hook, script, tmp_path)


def test_the_lock_wait_comes_from_kb_lock_wait() -> None:
    assert setup._wait({}) == 30
    assert setup._wait({"KB_LOCK_WAIT": "3"}) == 3
    with pytest.raises(KbError, match="KB_LOCK_WAIT"):
        setup._wait({"KB_LOCK_WAIT": "soon"})


def test_refusals_carry_the_setup_label_once() -> None:
    assert setup._labelled("cannot read") == "setup: cannot read"
    assert setup._labelled("setup: already labelled") == "setup: already labelled"
