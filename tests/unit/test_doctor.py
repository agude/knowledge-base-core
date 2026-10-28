"""kb doctor in process: the gatherers' branches that the end-to-end tests do not reach."""

import json
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import diagnosis, setup_rules
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


def test_hook_commands_skip_every_unexpected_shape() -> None:
    hooks = {
        "SessionStart": [{"hooks": [{"command": "bash a.sh"}, {"command": 3}, "text"]}],
        "Stop": "not a list",
        "Odd": ["not a group", {"hooks": "not a list"}],
    }

    assert doctor._hook_commands(hooks) == [("SessionStart", "bash a.sh")]
    assert doctor._hook_commands("not a mapping") == []


def test_claude_allow_reads_only_a_list_of_strings(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    assert doctor._claude_allow(settings) is None
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(x)", 4]}}), encoding="utf-8")
    assert doctor._claude_allow(settings) == ["Bash(x)"]
    settings.write_text(json.dumps({"permissions": {"allow": "Bash(x)"}}), encoding="utf-8")
    assert doctor._claude_allow(settings) is None


def test_codex_rules_concatenate_the_rules_files(tmp_path: Path) -> None:
    assert doctor._codex_rules(tmp_path / "absent") is None
    (tmp_path / "empty").mkdir()
    assert doctor._codex_rules(tmp_path / "empty") is None
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "a.rules").write_text('prefix_rule(pattern = ["kb"])\n', encoding="utf-8")
    assert doctor._codex_rules(rules) == 'prefix_rule(pattern = ["kb"])\n'


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


def test_coat_tree_entries_for_the_knowledge_base_are_named(tmp_path: Path) -> None:
    hooks = tmp_path / "xdg" / "coat-tree" / "hooks.d"
    (hooks / "Stop").mkdir(parents=True)
    (hooks / "Stop" / "010.knowledge.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (hooks / "Stop" / "020.other.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    ctx = context(tmp_path, environ={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})

    assert doctor._coat_tree_findings(ctx) == ["coat-tree Stop/010.knowledge.sh -> a regular file"]


@SKIP_LINKS
def test_coat_tree_links_name_their_targets(tmp_path: Path) -> None:
    hooks = tmp_path / "home" / ".config" / "coat-tree" / "hooks.d" / "PreToolUse"
    hooks.mkdir(parents=True)
    (hooks / "010.knowledge").symlink_to(tmp_path / "old" / "pretool-allow")
    ctx = context(tmp_path, home=tmp_path / "home")

    assert doctor._coat_tree_findings(ctx) == [
        f"coat-tree PreToolUse/010.knowledge -> {tmp_path / 'old' / 'pretool-allow'}"
    ]


def test_claude_and_codex_hook_entries_that_mention_the_knowledge_base_are_named(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "run ~/Knowledge/hook"}]}]}}),
        encoding="utf-8",
    )
    script = tmp_path / "shim.sh"
    script.write_text("# delegates to the knowledge-base adapter\n", encoding="utf-8")
    other = tmp_path / "other.sh"
    other.write_text("# nothing here\n", encoding="utf-8")
    hooks = tmp_path / "hooks.json"
    hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {"hooks": [{"command": f"bash {script}"}, {"command": f"bash {other}"}]}
                    ],
                    "Start": [{"hooks": [{"command": ""}]}],
                }
            }
        ),
        encoding="utf-8",
    )

    assert doctor._claude_hook_findings(settings) == [
        "Claude settings Stop hook: run ~/Knowledge/hook"
    ]
    assert doctor._codex_hook_findings(hooks) == [f"Codex Stop hook: bash {script}"]


@SKIP_LINKS
def test_skill_links_into_the_old_checkout_are_named(tmp_path: Path) -> None:
    old = tmp_path / "Knowledge"
    (old / "skills" / "curate").mkdir(parents=True)
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "curate").symlink_to(old / "skills" / "curate")
    (skills / "elsewhere").symlink_to(tmp_path / "Other")
    (skills / "plain").mkdir()

    assert doctor._skill_findings(skills, old) == [
        f"skill link {skills / 'curate'} -> {(old / 'skills' / 'curate').resolve()}"
    ]
    assert doctor._skill_findings(tmp_path / "absent", old) == []


@SKIP_LINKS
def test_a_content_hook_linked_into_the_old_tooling_is_named(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    old = tmp_path / "Knowledge" / "scripts" / "hooks" / "pre-commit"
    old.parent.mkdir(parents=True)
    old.write_text("old\n", encoding="utf-8")
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    if sys.platform != "win32":
        hook.symlink_to(old)
        assert doctor._content_hook_findings(tmp_path) == [f"content pre-commit link -> {old}"]
    outside = tmp_path_factory.mktemp("not-a-repository")
    assert doctor._content_hook_findings(outside) == []


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
        "allow-rules",
        "legacy",
    ]
    assert checks[2] == Check(
        "content", "fail", "no content root; see the config check", diagnosis.CONFIG_FIX
    )
    assert checks[9].state == "warn"
    assert checks[9].message.startswith("cannot check: no content root")


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
        Check("hook", "warn", "a symbolic link", "run kb setup --replace-old-hook"),
    ]
    monkeypatch.setattr(doctor, "gather", lambda ctx: checks)
    monkeypatch.setenv("KB_NOW", "2026-10-26T12:00:00Z")

    assert doctor.run([]) == 0
    assert capsys.readouterr().out == (
        "PASS version: kb 0.1.0\n"
        "WARN hook: a symbolic link\n"
        "  fix: run kb setup --replace-old-hook\n"
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
