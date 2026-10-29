"""kb doctor in process: the gatherers' branches that the end-to-end tests do not reach."""

import json
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import diagnosis, setup_rules, sync_state
from kb.commands import doctor
from kb.diagnosis import Check
from kb.errors import KbError

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
SKIP_LINKS = pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privilege")


def context(tmp_path: Path, **overrides: object) -> doctor.Context:
    values: dict[str, object] = {
        "environ": {},
        "configuration": tmp_path / "missing" / "config.toml",
        "home": tmp_path / "home",
        "platform": "win32",
        "now": NOW,
    }
    values.update(overrides)
    return doctor.Context(**values)  # type: ignore[arg-type]


def fake_kb(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "kb"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_the_store_root_comes_from_the_environment_or_the_default(tmp_path: Path) -> None:
    assert doctor._store({"X": str(tmp_path / "a")}, "X", tmp_path / "d") == tmp_path / "a"
    assert doctor._store({}, "X", tmp_path / "d") == tmp_path / "d"


def test_json_objects_are_read_or_defaulted_and_bad_json_is_reported(tmp_path: Path) -> None:
    assert doctor._json_object(tmp_path / "absent.json") == {}
    listed = tmp_path / "list.json"
    listed.write_text("[1]", encoding="utf-8")
    assert doctor._json_object(listed) == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(KbError, match="cannot read"):
        doctor._json_object(broken)


def test_read_text_is_none_for_absent_or_undecodable_files(tmp_path: Path) -> None:
    binary = tmp_path / "binary"
    binary.write_bytes(b"\xff\xfe")

    assert doctor._read_text(tmp_path / "absent") is None
    assert doctor._read_text(binary) is None


def test_the_claude_retention_is_the_setting_or_the_default(tmp_path: Path) -> None:
    assert doctor._claude_retention(tmp_path) == "for 30 days (default)"
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"cleanupPeriodDays": 365}), encoding="utf-8")
    assert doctor._claude_retention(tmp_path) == "for 365 days (cleanupPeriodDays)"
    settings.write_text(json.dumps({"cleanupPeriodDays": "many"}), encoding="utf-8")
    assert doctor._claude_retention(tmp_path) == "for 30 days (default)"


def test_claude_allow_reads_only_a_list_of_strings(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    assert doctor._claude_allow(settings) is None
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(x)", 4]}}), encoding="utf-8")
    assert doctor._claude_allow(settings) == ["Bash(x)"]
    settings.write_text(json.dumps({"permissions": {"allow": "Bash(x)"}}), encoding="utf-8")
    assert doctor._claude_allow(settings) is None


def test_codex_rules_concatenate_regular_files_and_name_linked_ones(tmp_path: Path) -> None:
    assert doctor._codex_rules(tmp_path / "absent") == (None, ())
    (tmp_path / "empty").mkdir()
    assert doctor._codex_rules(tmp_path / "empty") == (None, ())
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "a.rules").write_text('prefix_rule(pattern = ["kb"])\n', encoding="utf-8")
    assert doctor._codex_rules(rules) == ('prefix_rule(pattern = ["kb"])\n', ())
    (rules / "b.rules").symlink_to(rules / "a.rules")
    assert doctor._codex_rules(rules) == ('prefix_rule(pattern = ["kb"])\n', ("b.rules",))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#!/bin/sh\n# marker\n", "managed hook names no kb path"),
        ("#!/bin/sh\n# marker\nexec something else\n", "managed hook names no kb path"),
    ],
)
def test_a_managed_hook_without_a_kb_path_is_a_problem(text: str, expected: str) -> None:
    assert doctor._kb_problem(text.encode("utf-8")) == expected


@pytest.mark.skipif(sys.platform == "win32", reason="the test runs a POSIX shell script as kb")
def test_the_kb_path_of_a_managed_hook_must_exist_and_print_a_version(tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    assert doctor._kb_problem(setup_rules.hook_script(str(missing)).encode()) == (
        f"kb path is missing: {missing}"
    )
    plain = tmp_path / "plain"
    plain.write_text("not executable\n", encoding="utf-8")
    assert doctor._kb_problem(setup_rules.hook_script(str(plain)).encode()) == (
        f"kb path does not run: {plain}"
    )
    wrong = fake_kb(tmp_path / "wrong", "#!/bin/sh\necho other\n")
    assert doctor._kb_problem(setup_rules.hook_script(str(wrong)).encode()) == (
        f"kb path does not print a kb version: {wrong}"
    )
    right = fake_kb(tmp_path / "right", '#!/bin/sh\necho "kb 0.1.0"\n')
    assert doctor._kb_problem(setup_rules.hook_script(str(right)).encode()) is None


def test_a_gatherer_error_becomes_a_named_check() -> None:
    def broken() -> Check:
        raise KbError("disk gone")

    check = doctor._guarded("capture", "warn", broken)

    assert check == Check(
        "capture", "warn", "cannot check: disk gone", "fix the cause, then run kb doctor again"
    )


def test_config_names_the_environment_or_the_file_as_its_source(tmp_path: Path) -> None:
    content = tmp_path / "content"
    content.mkdir()
    result, root = doctor._config(context(tmp_path, environ={"KB_CONTENT": str(content)}))
    assert (result.state, root) == ("pass", content.resolve())
    assert result.message.endswith("(from KB_CONTENT)")

    missing, none = doctor._config(context(tmp_path))
    assert none is None
    assert missing.state == "fail"
    assert "no content repository" in missing.message


def test_gather_reports_every_check_when_nothing_is_configured(tmp_path: Path) -> None:
    checks = doctor.gather(context(tmp_path))

    assert [check.name for check in checks] == [
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
    ]
    assert checks[2] == Check(
        "content", "fail", "no content root; see the config check", diagnosis.CONFIG_FIX
    )
    assert checks[9].state == "warn"
    assert checks[9].message.startswith("cannot check: no content root")
    assert checks[10] == Check(
        "skills",
        "warn",
        "Claude Code knowledge-base is missing; Claude Code curate is missing; "
        "Codex knowledge-base is missing; Codex curate is missing",
        "run kb setup",
    )


def test_the_scheduler_is_queried_through_the_platform_or_skipped(tmp_path: Path) -> None:
    assert (
        doctor._scheduler(context(tmp_path, platform="darwin")).message == "not checked on darwin"
    )


def test_a_missing_systemctl_is_a_scheduler_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    check = doctor._scheduler(context(tmp_path, platform="linux"))

    assert check.state == "warn"
    assert check.message.startswith("cannot query systemctl:")


def test_run_prints_each_check_with_its_fix_and_exits_by_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checks = [
        Check("version", "pass", "kb 0.1.0"),
        Check("hook", "warn", "a symbolic link", "run kb setup"),
    ]
    monkeypatch.setattr(doctor, "gather", lambda ctx: checks)
    monkeypatch.setenv("KB_NOW", "2026-10-26T12:00:00Z")

    assert doctor.run([]) == 0
    assert capsys.readouterr().out == (
        "PASS version: kb 0.1.0\nWARN hook: a symbolic link\n  fix: run kb setup\n"
    )

    monkeypatch.setattr(
        doctor, "gather", lambda ctx: [Check("sync", "fail", "No record", "run kb sync")]
    )
    assert doctor.run([]) == 1


def test_run_takes_no_options_and_prints_its_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert doctor.run(["--help"]) == 0
    assert capsys.readouterr().out.startswith("Usage: kb doctor")
    with pytest.raises(KbError, match="Usage: kb doctor"):
        doctor.run(["extra"])


def test_the_git_helper_never_asks_for_optional_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Mapping[str, str]] = []

    def record(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert isinstance(env, dict)
        seen.append(env)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", record)

    doctor._git(tmp_path, "status")

    assert seen[0]["GIT_OPTIONAL_LOCKS"] == "0"


def test_content_check_names_a_root_that_is_not_a_repository(tmp_path: Path) -> None:
    assert doctor._content(tmp_path) == diagnosis.content_check(
        False, None, False, 0, False, None, None
    )


def test_dirty_count_refuses_a_root_that_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="cannot inspect working tree"):
        doctor._dirty_count(tmp_path)


def test_gitattributes_refuses_a_root_that_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="cannot read attributes"):
        doctor._gitattributes(tmp_path)


def test_hook_refuses_a_root_that_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="cannot locate the hooks directory"):
        doctor._hook(tmp_path)


def test_sync_refuses_a_root_that_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="cannot locate the Git directory"):
        doctor._sync(tmp_path, context(tmp_path))


def test_sync_reports_an_unreadable_record_in_a_repository(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    record = sync_state.path(tmp_path / ".git")
    record.parent.mkdir(parents=True)
    record.write_text("not json\n", encoding="utf-8")

    result = doctor._sync(tmp_path, context(tmp_path))

    assert result.state == "fail"
    assert result.message.startswith("record unreadable: sync state: invalid JSON")
