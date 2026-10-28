"""The pure doctor checks: each state of each check, and the rules that judge the host files."""

from datetime import UTC, datetime, timedelta

import pytest

from kb import diagnosis, setup_rules
from kb.diagnosis import Check
from kb.sync_state import SyncState

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
CANONICAL = setup_rules.instruction_block("/data/content")
CLAUDE_RULES = [f"Bash(kb {word} *)" for word in setup_rules.WORKING_COMMANDS]


def record(
    outcome: str = "ok", exchange: datetime | None = NOW, message: str | None = None
) -> SyncState:
    return SyncState("0.1.0", NOW, outcome, exchange, message)


def test_the_version_check_always_passes() -> None:
    assert diagnosis.version_check("0.1.0", "3.15.0") == Check(
        "version", "pass", "kb 0.1.0, Python 3.15.0"
    )


def test_the_config_check_names_its_source_or_fails_with_the_problem() -> None:
    passed = diagnosis.config_check("KB_CONTENT", "/data/content", None)
    failed = diagnosis.config_check("config.toml", None, "no content setting")

    assert passed.state == "pass"
    assert passed.message == "content root /data/content (from KB_CONTENT)"
    assert (failed.state, failed.message) == ("fail", "no content setting")
    assert failed.fix == diagnosis.CONFIG_FIX
    assert diagnosis.config_check("x", None, None).message == "no content root"


@pytest.mark.parametrize(
    ("args", "state", "message"),
    [
        ((False, None, False, 0, False, None, None), "fail", "not a Git repository"),
        ((True, None, True, 0, False, None, None), "fail", "detached HEAD"),
        ((True, "main", False, 0, False, None, None), "fail", "no origin remote"),
        ((True, "main", True, 0, True, 0, 0), "pass", "branch main, clean, level with origin/main"),
        ((True, "main", True, 2, True, 0, 0), "warn", "2 changed path(s) in the worktree"),
        ((True, "main", True, 0, False, None, None), "warn", "origin/main has not been fetched"),
        ((True, "main", True, 0, True, 3, 0), "warn", "3 unpublished commit(s)"),
        ((True, "main", True, 0, True, 0, 4), "warn", "4 commit(s) not yet pulled from origin"),
    ],
)
def test_the_content_check_states(args: tuple[object, ...], state: str, message: str) -> None:
    check = diagnosis.content_check(*args)  # type: ignore[arg-type]

    assert check.state == state
    assert check.message.startswith(message)


def test_the_content_check_reports_every_problem_at_once() -> None:
    check = diagnosis.content_check(True, "main", True, 1, True, 2, 3)

    assert check.state == "warn"
    assert check.message == (
        "1 changed path(s) in the worktree; 2 unpublished commit(s); "
        "3 commit(s) not yet pulled from origin"
    )


def test_the_gitattributes_check_requires_text_auto_and_eol_lf() -> None:
    assert diagnosis.gitattributes_check("auto", "lf").state == "pass"
    missing = diagnosis.gitattributes_check("unspecified", "unspecified")

    assert missing.state == "warn"
    assert missing.message == "text=unspecified, eol=unspecified"
    assert missing.fix is not None and "text=auto eol=lf" in missing.fix


@pytest.mark.parametrize(
    ("kind", "old_link", "managed", "problem", "state", "message"),
    [
        ("absent", False, False, None, "fail", "absent"),
        ("link", True, False, None, "warn", "a symbolic link to the old tooling's hook"),
        ("link", False, False, None, "fail", "not installed by kb"),
        ("other", False, False, None, "fail", "not installed by kb"),
        ("file", False, False, None, "fail", "not installed by kb"),
        ("file", False, True, "kb path is missing: /x", "fail", "kb path is missing: /x"),
        ("file", False, True, None, "pass", "installed by kb setup; its kb runs --version"),
    ],
)
def test_the_hook_check_states(
    kind: str, old_link: bool, managed: bool, problem: str | None, state: str, message: str
) -> None:
    check = diagnosis.hook_check(kind, old_link, managed, problem)

    assert (check.state, check.message) == (state, message)


def test_the_curation_check_passes_without_findings_and_warns_with_them() -> None:
    assert diagnosis.curation_check(()) == Check("curation", "pass", "no unsettled batch")

    warned = diagnosis.curation_check(("batch B has unsettled work; run: kb curate status B",))

    assert warned.state == "warn"
    assert "kb curate status B" in warned.message


def test_the_sync_check_covers_every_record_state() -> None:
    assert diagnosis.sync_check(None, "bad json", NOW).message == "record unreadable: bad json"
    assert diagnosis.sync_check(None, None, NOW) == Check(
        "sync", "fail", "No record", "run kb sync"
    )
    dirty = diagnosis.sync_check(record("dirty", None, None), None, NOW)
    assert dirty.state == "warn"
    assert dirty.message == "last run ended dirty"
    failed = diagnosis.sync_check(record("error", NOW, "sync: push failed"), None, NOW)
    assert failed.message == "last run ended error: sync: push failed"
    never = diagnosis.sync_check(record("ok", None, None), None, NOW)
    assert (never.state, never.message) == ("warn", "no successful exchange recorded")
    stale = diagnosis.sync_check(record(), None, NOW + timedelta(minutes=61))
    assert stale.state == "warn"
    assert stale.message == "last exchange 2026-10-26T12:00:00Z, older than 60 minutes"
    fresh = diagnosis.sync_check(record(), None, NOW + timedelta(minutes=60))
    assert (fresh.state, fresh.message) == ("pass", "last exchange 2026-10-26T12:00:00Z")


def test_the_scheduler_is_checked_only_on_linux() -> None:
    assert diagnosis.scheduler_check("linux", "enabled", "active", None).state == "pass"
    windows = diagnosis.scheduler_check("win32", None, None, None)
    assert (windows.state, windows.message) == ("warn", "not checked on win32")
    darwin = diagnosis.scheduler_check("darwin", None, None, None)
    assert darwin.message == "not checked on darwin"
    missing = diagnosis.scheduler_check("linux", None, None, "no systemctl")
    assert (missing.state, missing.message) == ("warn", "cannot query systemctl: no systemctl")
    inactive = diagnosis.scheduler_check("linux", "disabled", "inactive", None)
    assert inactive.message == "kb-sync.timer is disabled and inactive"


def test_the_capture_check_covers_each_warning_and_the_pass() -> None:
    passed = diagnosis.capture_check(True, (), 0, "for 30 days (default)", "unknown", None)
    assert passed.state == "pass"
    disabled = diagnosis.capture_check(False, (), None, "for 30 days (default)", "unknown", None)
    assert disabled.message == "Capture disabled (harvest_since unset)"
    assert disabled.fix == "remove old capture hooks, then run kb setup --enable-capture"
    unreadable = diagnosis.capture_check(True, ("/x",), None, "d", "unknown", None)
    assert unreadable.message == "unreadable transcript root: /x"
    aging = diagnosis.capture_check(
        True, (), 2, "for 36500 days (cleanupPeriodDays)", "unknown", None
    )
    assert aging.state == "warn"
    assert aging.message.startswith("2 ready transcript(s) older than 20 days")
    assert "for 36500 days (cleanupPeriodDays)" in aging.message
    assert "Codex retention is unknown" in aging.message
    failed = diagnosis.capture_check(True, (), None, "d", "unknown", "no HEAD")
    assert failed.message == "cannot check capture: no HEAD"


def test_the_instructions_and_allow_checks_name_each_host() -> None:
    assert diagnosis.instructions_check({"claude": None, "codex": None}).state == "pass"
    bad = diagnosis.instructions_check({"claude": "no global file", "codex": None})
    assert (bad.state, bad.message) == ("warn", "claude: no global file")
    assert diagnosis.allow_rules_check({"claude": (), "codex": ()}).state == "pass"
    rules = diagnosis.allow_rules_check({"claude": ("missing x",), "codex": ()})
    assert (rules.state, rules.message) == ("warn", "claude: missing x")


def test_the_legacy_check_names_each_registration() -> None:
    assert diagnosis.legacy_check(()) == Check(
        "legacy", "pass", "no old-tooling registration found"
    )
    warned = diagnosis.legacy_check(("coat-tree a", "skill link b"))
    assert warned.message == "2 old-tooling registration(s): coat-tree a; skill link b"


def test_an_instruction_file_without_the_canonical_block_has_a_named_problem() -> None:
    assert diagnosis.instruction_problem(None, CANONICAL) == "no global file"
    assert diagnosis.instruction_problem("plain text\n", CANONICAL) == "no kb block"
    open_block = setup_rules.BEGIN_MARKER + "\nno end\n"
    assert diagnosis.instruction_problem(open_block, CANONICAL) == "kb block has no end marker"
    edited = CANONICAL.replace("holds durable facts", "holds other facts")
    assert diagnosis.instruction_problem(edited, CANONICAL) == (
        "block differs from the canonical block"
    )


def test_the_canonical_block_is_found_inside_a_larger_file() -> None:
    surrounding = "# My notes\n\n" + CANONICAL + "\nmore\n"

    assert diagnosis.instruction_problem(surrounding, CANONICAL) is None


def test_claude_rules_missing_broader_and_colon_form() -> None:
    assert diagnosis.claude_allow_problems(None) == ("no permissions.allow list",)
    assert diagnosis.claude_allow_problems(CLAUDE_RULES) == ()
    colon = [rule.replace(" *)", ":*)") for rule in CLAUDE_RULES]
    assert diagnosis.claude_allow_problems(colon) == ()
    partial = diagnosis.claude_allow_problems([*CLAUDE_RULES[1:], "Bash(kb *)"])
    assert partial[0] == "missing Bash(kb recall *)"
    assert "broader Bash(kb *)" in partial
    assert diagnosis.claude_allow_problems(["Bash(npm test *)"])[-1] == "missing Bash(kb recall *)"


def test_codex_rules_missing_broader_and_decision_aware() -> None:
    assert diagnosis.codex_allow_problems(None) == ("no rules files",)
    complete = setup_rules.allow_codex()
    assert diagnosis.codex_allow_problems(complete) == ()
    prompted = complete.replace('"gap"], decision = "allow"', '"gap"], decision = "prompt"')
    assert diagnosis.codex_allow_problems(prompted) == ("missing kb gap",)
    broader = complete + 'prefix_rule(pattern = ["kb"], decision = "allow")\n'
    assert diagnosis.codex_allow_problems(broader) == ("broader kb",)
    unrelated = complete + 'prefix_rule(pattern = ["git", "status"], decision = "allow")\n'
    assert diagnosis.codex_allow_problems(unrelated) == ()
    no_decision = complete.replace('decision = "allow"', 'justification = "x"')
    assert diagnosis.codex_allow_problems(no_decision) == ()
    preamble = complete.split("prefix_rule(")[0]
    assert diagnosis.codex_allow_problems(preamble) == tuple(
        f"missing kb {word}" for word in setup_rules.WORKING_COMMANDS
    )
    pattern_less = 'prefix_rule(decision = "allow")\n' + complete
    assert diagnosis.codex_allow_problems(pattern_less) == ()
