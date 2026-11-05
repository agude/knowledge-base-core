"""kb doctor's gatherers in process, on a configured machine built in a temporary directory.

These run the Git and host-file gatherers directly, so their branches count toward coverage.
The end-to-end tests run the same checks in a subprocess, which coverage does not measure.
"""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kb import setup_rules, skills, sync_state, token_cache
from kb.commands import doctor
from kb.diagnosis import Check
from kb.sync_state import SyncState

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
GOOSE_SCRIPT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "transcripts" / "goose" / "sessions.sql"
)


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
    (root / ".gitignore").write_text("/cache/\n", encoding="utf-8")
    git(root, "add", ".gitattributes", ".gitignore")
    git(root, "commit", "-q", "-m", "Attributes and ignores")
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-q", "--set-upstream", "origin", "main")
    if sys.platform == "win32":
        kb = fake_tool(tmp_path / "bin", "kb.cmd", "@echo kb 0.1.0\n")
    else:
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
    (claude / "settings.json").write_text(setup_rules.allow_claude(sys.platform), encoding="utf-8")
    (codex / "rules").mkdir(parents=True)
    (codex / "AGENTS.md").write_text(canonical, encoding="utf-8")
    (codex / "rules" / "kb.rules").write_text(setup_rules.allow_codex(), encoding="utf-8")
    for directory in (claude / "skills", home / ".agents" / "skills"):
        for name in skills.SKILL_NAMES:
            skills.install(directory / name, skills.package_files(name), "0.1.0")
    configuration = tmp_path / "config.toml"
    configuration.write_text(
        f'content = "{root.as_posix()}"\nharvest_since = 2026-10-24T00:00:00Z\n', encoding="utf-8"
    )
    if sys.platform == "win32":
        # Windows runs no sh script by name, so the systemctl answers come from Python.
        answers = tuple(
            (sys.executable, "-c", f"print('{word}')") for word in ("enabled", "active")
        )
        monkeypatch.setattr(doctor, "scheduler_commands", lambda platform: answers)
    else:
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


def test_a_configured_machine_passes_every_gathered_check(machine: doctor.Context) -> None:
    token_cache.refresh(Path(machine.environ["KB_CONTENT"]))
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
            "cache",
            "scheduler",
            "capture",
            "instructions",
            "skills",
            "allow-rules",
        ),
        "pass",
    )


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


def test_the_hook_states_are_each_named(machine: doctor.Context, tmp_path: Path) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    hook = root / ".git" / "hooks" / "pre-commit"
    foreign = "#!/bin/sh\necho mine\n"
    hook.write_text(foreign, encoding="utf-8")

    assert by_name(doctor.gather(machine))["hook"].message == "not installed by kb"

    target = tmp_path / "elsewhere" / "pre-commit"
    target.parent.mkdir(parents=True)
    target.write_text("other\n", encoding="utf-8")
    hook.unlink()
    hook.symlink_to(target)

    assert by_name(doctor.gather(machine))["hook"].message == "not installed by kb"

    hook.unlink()
    assert by_name(doctor.gather(machine))["hook"].message == "absent"


def test_a_managed_hook_whose_kb_is_missing_fails(machine: doctor.Context, tmp_path: Path) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(setup_rules.hook_script(str(tmp_path / "gone")), encoding="utf-8")
    hook.chmod(0o755)

    check = by_name(doctor.gather(machine))["hook"]

    assert check.state == "fail"
    assert check.message == f"kb path is missing: {tmp_path / 'gone'}"


def test_gitattributes_and_sync_report_their_states(machine: doctor.Context) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    (root / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    attributes = by_name(doctor.gather(machine))["gitattributes"]

    assert attributes.message == "text=auto, eol=unspecified"

    (root / ".git" / "kb" / "sync-state.json").unlink()
    assert by_name(doctor.gather(machine))["sync"].message == "No record"


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


def test_capture_checks_the_goose_root_and_counts_its_old_ready_sessions(
    machine: doctor.Context, tmp_path: Path
) -> None:
    goose_root = tmp_path / "goose"
    sessions = goose_root / "data" / "sessions"
    sessions.mkdir(parents=True)
    with closing(sqlite3.connect(sessions / "sessions.db")) as connection:
        connection.executescript(GOOSE_SCRIPT.read_text(encoding="utf-8"))
    context = replace(machine, environ={**machine.environ, "GOOSE_PATH_ROOT": str(goose_root)})

    assert by_name(doctor.gather(context))["capture"].state == "pass"
    later = replace(context, now=NOW + timedelta(days=30))
    old = by_name(doctor.gather(later))["capture"]
    assert old.message.startswith("2 ready transcript(s) older than 20 days")

    sessions.chmod(0)
    try:
        if os.access(sessions, os.R_OK | os.X_OK):
            pytest.skip("this account can read a directory with mode 0")
        unreadable = by_name(doctor.gather(context))["capture"]
        assert unreadable.message == f"unreadable transcript root: {sessions}"
    finally:
        sessions.chmod(0o755)


def test_capture_without_a_harvest_cutoff_reports_it_and_no_root_reports_the_problem(
    machine: doctor.Context,
) -> None:
    machine.configuration.write_text(
        f'content = "{Path(machine.environ["KB_CONTENT"]).as_posix()}"\n', encoding="utf-8"
    )
    off = by_name(doctor.gather(machine))["capture"]

    assert off.message == "Capture disabled (harvest_since unset)"

    machine.configuration.write_text(
        f'content = "{Path(machine.environ["KB_CONTENT"]).as_posix()}"\nharvest_since = 2026-10-24T00:00:00Z\n',
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


def test_a_host_file_without_the_policy_line_passes_the_instructions_check(
    machine: doctor.Context,
) -> None:
    bare = setup_rules.instruction_block_without_policy()
    claude = Path(machine.environ["CLAUDE_CONFIG_DIR"])
    codex = Path(machine.environ["CODEX_HOME"])
    (claude / "CLAUDE.md").write_text(bare, encoding="utf-8")
    (codex / "AGENTS.md").write_text(bare, encoding="utf-8")

    assert by_name(doctor.gather(machine))["instructions"].state == "pass"


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


def test_scheduler_and_curation_gather_through_their_commands(machine: doctor.Context) -> None:
    checks = by_name(doctor.gather(machine))

    assert checks["scheduler"].message == "kb-sync.timer is enabled and active"
    assert checks["curation"].message == "no unsettled batch"
    assert doctor._stdout(("sh", "-c", "echo hi")) == "hi"


def test_the_cache_check_names_each_state(machine: doctor.Context) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    missing = doctor._cache(root)
    assert (missing.state, missing.message.split(":")[0], missing.fix) == (
        "warn",
        "missing",
        "run kb sync",
    )

    token_cache.refresh(root)
    current = doctor._cache(root)
    assert (current.state, current.message.endswith("current")) == ("pass", True)

    write = root / "observations" / "pending" / "20261026T120000-new.md"
    write.parent.mkdir(parents=True)
    write.write_text("---\ntitle: New\n---\n\nNew note.\n", encoding="utf-8")
    stale = doctor._cache(root)
    assert (stale.state, stale.message.split(":")[0], stale.fix) == (
        "warn",
        "stale",
        "run kb sync",
    )


def test_a_cache_that_git_does_not_ignore_warns_with_the_fix(machine: doctor.Context) -> None:
    root = Path(machine.environ["KB_CONTENT"])
    (root / ".gitignore").write_text("", encoding="utf-8")
    check = doctor._cache(root)
    assert (check.state, check.message.split(":")[0]) == ("warn", "not written")
    assert check.fix is not None and "/cache/" in check.fix


def test_a_content_root_that_is_not_a_worktree_has_no_cache_to_check(tmp_path: Path) -> None:
    check = doctor._cache(tmp_path)
    assert (check.name, check.state) == ("cache", "pass")
    assert check.message.startswith("not used: content is not a git worktree")
