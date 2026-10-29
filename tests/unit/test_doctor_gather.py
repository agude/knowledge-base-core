"""kb doctor's gatherers in process, on a configured machine built in a temporary directory.

These run the Git and host-file gatherers directly, so their branches count toward coverage.
The end-to-end tests run the same checks in a subprocess, which coverage does not measure.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import setup_rules, skills, sync_state
from kb.commands import doctor
from kb.diagnosis import Check
from kb.sync_state import SyncState

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
SKIP = pytest.mark.skipif(sys.platform == "win32", reason="the gatherers use POSIX tools here")


def git(root: Path, *words: str) -> str:
    result = subprocess.run(
        ["git", *words],
        cwd=root,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@x.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@x.invalid",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def fake_tool(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> doctor.Context:
    """A configured machine: a repository with origin, the hook, the sync record, host files."""
    root = tmp_path / "content"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / ".gitattributes").write_text("* text=auto eol=lf\n", encoding="utf-8")
    git(root, "add", ".gitattributes")
    git(root, "commit", "-q", "-m", "Attributes")
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-q", "--set-upstream", "origin", "main")
    kb = fake_tool(tmp_path / "bin", "kb", '#!/bin/sh\necho "kb 0.1.0"\n')
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(setup_rules.hook_script(str(kb)), encoding="utf-8")
    hook.chmod(0o755)
    sync_state.write(root / ".git", SyncState("0.1.0", NOW, "ok", NOW, None))
    home = tmp_path / "home"
    claude, codex = home / ".claude", home / ".codex"
    canonical = setup_rules.instruction_block(str(root))
    claude.mkdir(parents=True)
    (claude / "CLAUDE.md").write_text(canonical, encoding="utf-8")
    (claude / "settings.json").write_text(setup_rules.allow_claude(), encoding="utf-8")
    (codex / "rules").mkdir(parents=True)
    (codex / "AGENTS.md").write_text(canonical, encoding="utf-8")
    (codex / "rules" / "kb.rules").write_text(setup_rules.allow_codex(), encoding="utf-8")
    for directory in (claude / "skills", home / ".agents" / "skills"):
        for name in skills.SKILL_NAMES:
            skills.install(
                directory / name,
                skills.package_files(name),
                "0.1.0",
                home / "Knowledge",
            )
    configuration = tmp_path / "config.toml"
    configuration.write_text(
        f'content = "{root}"\nharvest_since = 2026-10-24T00:00:00Z\n', encoding="utf-8"
    )
    systemctl = fake_tool(
        tmp_path / "systemd",
        "systemctl",
        '#!/bin/sh\ncase "$2" in\n  is-enabled) echo enabled ;;\n  is-active) echo active ;;\nesac\n',
    )
    monkeypatch.setenv("PATH", f"{systemctl.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    environ = {
        "KB_CONTENT": str(root),
        "CLAUDE_CONFIG_DIR": str(claude),
        "CODEX_HOME": str(codex),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
    }
    return doctor.Context(
        environ=environ,
        configuration=configuration,
        home=home,
        platform="linux",
        now=NOW,
    )


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {check.name: check for check in checks}


@SKIP
def test_a_configured_machine_passes_every_gathered_check(machine: doctor.Context) -> None:
    checks = by_name(doctor.gather(machine))

    assert {name: check.state for name, check in checks.items()} == dict.fromkeys(
        (
            "version",
            "config",
            "content",
            "gitattributes",
            "hook",
            "curation",
            "sync",
            "scheduler",
            "capture",
            "instructions",
            "skills",
            "allow-rules",
            "legacy",
        ),
        "pass",
    )


@SKIP
def test_content_reports_missing_origin_unfetched_and_dirty_states(machine: doctor.Context) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    (root / "scratch.txt").write_text("x\n", encoding="utf-8")
    dirty = by_name(doctor.gather(machine))["content"]

    assert (dirty.state, dirty.message) == ("warn", "1 changed path(s) in the worktree")

    (root / "scratch.txt").unlink()
    git(root, "commit", "-q", "--allow-empty", "-m", "Local only")
    ahead = by_name(doctor.gather(machine))["content"]

    assert (ahead.state, ahead.message) == ("warn", "1 unpublished commit(s)")

    git(root, "remote", "remove", "origin")
    gone = by_name(doctor.gather(machine))["content"]

    assert (gone.state, gone.message) == ("fail", "no origin remote")


@SKIP
def test_the_hook_states_are_each_named(machine: doctor.Context, tmp_path: Path) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    hook = root / ".git" / "hooks" / "pre-commit"
    foreign = "#!/bin/sh\necho mine\n"
    hook.write_text(foreign, encoding="utf-8")

    assert by_name(doctor.gather(machine))["hook"].message == "not installed by kb"

    old = tmp_path / "Knowledge" / "scripts" / "hooks" / "pre-commit"
    old.parent.mkdir(parents=True)
    old.write_text("old\n", encoding="utf-8")
    hook.unlink()
    hook.symlink_to(old)

    assert by_name(doctor.gather(machine))["hook"].state == "warn"

    hook.unlink()
    assert by_name(doctor.gather(machine))["hook"].message == "absent"


@SKIP
def test_a_managed_hook_whose_kb_is_missing_fails(machine: doctor.Context, tmp_path: Path) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(setup_rules.hook_script(str(tmp_path / "gone")), encoding="utf-8")
    hook.chmod(0o755)

    check = by_name(doctor.gather(machine))["hook"]

    assert check.state == "fail"
    assert check.message == f"kb path is missing: {tmp_path / 'gone'}"


@SKIP
def test_gitattributes_and_sync_report_their_states(machine: doctor.Context) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    (root / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    attributes = by_name(doctor.gather(machine))["gitattributes"]

    assert attributes.message == "text=auto, eol=unspecified"

    (root / ".git" / "kb" / "sync-state.json").unlink()
    assert by_name(doctor.gather(machine))["sync"].message == "No record"


@SKIP
def test_capture_passes_and_names_an_unreadable_transcript_root(
    machine: doctor.Context, tmp_path: Path
) -> None:
    store = Path(machine.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "demo"
    store.mkdir(parents=True)
    transcript = store / "main.jsonl"
    transcript.write_text("", encoding="utf-8")
    os.utime(transcript, (1756684800.0, 1756684800.0))

    check = by_name(doctor.gather(machine))["capture"]

    assert check.state == "pass"

    locked = Path(machine.environ["CODEX_HOME"]) / "sessions"
    locked.mkdir()
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK | os.X_OK):
            pytest.skip("this account can read a directory with mode 0")
        unreadable = by_name(doctor.gather(machine))["capture"]
        assert unreadable.message == f"unreadable transcript root: {locked}"
    finally:
        locked.chmod(0o755)


@SKIP
def test_capture_without_a_harvest_cutoff_reports_it_and_no_root_reports_the_problem(
    machine: doctor.Context,
) -> None:
    machine.configuration.write_text(
        f'content = "{machine.environ["KB_CONTENT"]}"\n', encoding="utf-8"
    )
    off = by_name(doctor.gather(machine))["capture"]

    assert off.message == "Capture disabled (harvest_since unset)"

    machine.configuration.write_text(
        f'content = "{machine.environ["KB_CONTENT"]}"\nharvest_since = 2026-10-24T00:00:00Z\n',
        encoding="utf-8",
    )
    no_root = doctor._capture(
        doctor.Context(
            environ={"CLAUDE_CONFIG_DIR": machine.environ["CLAUDE_CONFIG_DIR"]},
            configuration=machine.configuration,
            home=machine.home,
            platform="linux",
            now=NOW,
        ),
        None,
    )

    assert no_root.message == "cannot check capture: no content root to read HEAD from"


@SKIP
def test_instructions_and_allow_rules_name_each_host_problem(machine: doctor.Context) -> None:
    claude = Path(machine.environ["CLAUDE_CONFIG_DIR"])
    (claude / "CLAUDE.md").write_text("notes\n", encoding="utf-8")
    (claude / "settings.json").write_text('{"permissions": {"allow": []}}\n', encoding="utf-8")
    checks = by_name(doctor.gather(machine))

    assert checks["instructions"].message == "claude: no kb block"
    assert checks["allow-rules"].message.startswith("claude: missing Bash(kb evidence *)")

    (claude / "settings.json").write_text("not json\n", encoding="utf-8")
    broken = by_name(doctor.gather(machine))["allow-rules"]

    assert broken.state == "warn"
    assert broken.message.startswith("cannot check: cannot read")


@SKIP
def test_allow_rules_ignore_a_symlinked_codex_rules_file(
    machine: doctor.Context, tmp_path: Path
) -> None:
    rules = Path(machine.environ["CODEX_HOME"]) / "rules"
    linked_source = tmp_path / "linked.rules"
    linked_source.write_text(setup_rules.allow_codex(), encoding="utf-8")
    (rules / "kb.rules").unlink()
    (rules / "kb.rules").symlink_to(linked_source)
    check = by_name(doctor.gather(machine))["allow-rules"]

    assert check.state == "warn"
    assert check.message == "codex: kb.rules is a symbolic link, which Codex skips; no rules files"


@SKIP
def test_legacy_names_a_content_hook_link_into_the_old_tooling(
    machine: doctor.Context, tmp_path: Path
) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    hook = root / ".git" / "hooks" / "pre-commit"
    old = tmp_path / "Knowledge" / "scripts" / "hooks" / "pre-commit"
    old.parent.mkdir(parents=True)
    old.write_text("old\n", encoding="utf-8")
    hook.unlink()
    hook.symlink_to(old)

    legacy = by_name(doctor.gather(machine))["legacy"]

    assert legacy.state == "warn"
    assert f"content pre-commit link -> {old}" in legacy.message


@SKIP
def test_scheduler_and_curation_gather_through_their_commands(machine: doctor.Context) -> None:
    checks = by_name(doctor.gather(machine))

    assert checks["scheduler"].message == "kb-sync.timer is enabled and active"
    assert checks["curation"].message == "no unsettled batch"
    assert doctor._stdout(("sh", "-c", "echo hi")) == "hi"
