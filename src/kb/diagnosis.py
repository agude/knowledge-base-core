"""Pure checks for `kb doctor`. Each takes facts that were already gathered, and returns a Check.

Nothing here reads the file system, runs Git, or reads the clock except through its arguments.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from kb import setup_rules
from kb.sync_state import SyncState

State = Literal["pass", "warn", "fail"]
SYNC_MAX_AGE = timedelta(minutes=60)
TRANSCRIPT_MAX_AGE = timedelta(days=20)
TIMER = "kb-sync.timer"
WORKING = setup_rules.WORKING_COMMANDS
EXPECTED_CLAUDE = frozenset(f"Bash(kb {command} *)" for command in WORKING)
EXPECTED_CODEX = frozenset(("kb", command) for command in WORKING)
PATTERN = re.compile(r"pattern\s*=\s*\[([^\]]*)\]")
DECISION = re.compile(r'decision\s*=\s*"(\w+)"')
QUOTED = re.compile(r'"([^"]*)"')
CONFIG_FIX = "set content to an existing content repository, with kb setup --content PATH"


@dataclass(frozen=True)
class Check:
    """One line of doctor output: a check's name, its state, its message, and its fix."""

    name: str
    state: State
    message: str
    fix: str | None = None


def version_check(kb_version: str, python_version: str) -> Check:
    """The installed kb version and the Python version that runs it."""
    return Check("version", "pass", f"kb {kb_version}, Python {python_version}")


def config_check(source: str, root: str | None, problem: str | None) -> Check:
    """Whether the content root resolves, and where its setting comes from."""
    if problem is None and root is not None:
        return Check("config", "pass", f"content root {root} (from {source})")
    return Check("config", "fail", problem or "no content root", CONFIG_FIX)


def content_check(
    repo: bool,
    branch: str | None,
    origin: bool,
    dirty: int,
    fetched: bool,
    ahead: int | None,
    behind: int | None,
) -> Check:
    """Whether the content root is a clean Git repository on a branch, level with origin."""
    fails: list[str] = []
    if not repo:
        return Check(
            "content",
            "fail",
            "not a Git repository",
            "make the content root a Git repository; kb setup --init creates one",
        )
    if branch is None:
        fails.append("detached HEAD")
    if not origin:
        fails.append("no origin remote")
    if fails:
        return Check("content", "fail", "; ".join(fails), "check out a branch and add origin")
    warnings: list[str] = []
    if dirty:
        warnings.append(f"{dirty} changed path(s) in the worktree")
    if not fetched:
        warnings.append(f"origin/{branch} has not been fetched")
    if ahead:
        warnings.append(f"{ahead} unpublished commit(s)")
    if behind:
        warnings.append(f"{behind} commit(s) not yet pulled from origin")
    if warnings:
        return Check("content", "warn", "; ".join(warnings), "run kb sync")
    return Check("content", "pass", f"branch {branch}, clean, level with origin/{branch}")


def gitattributes_check(text: str, eol: str) -> Check:
    """Whether `* text=auto eol=lf` is in effect for the content root."""
    if text == "auto" and eol == "lf":
        return Check("gitattributes", "pass", "* text=auto eol=lf is in effect")
    return Check(
        "gitattributes",
        "warn",
        f"text={text}, eol={eol}",
        "add the line `* text=auto eol=lf` to .gitattributes in the content root",
    )


def hook_check(kind: str, managed: bool, kb_problem: str | None) -> Check:
    """Whether the pre-commit hook is kb's, and whether the kb it names runs."""
    if kind == "absent":
        return Check("hook", "fail", "absent", "run kb setup")
    if kind in {"link", "other"} or (kind == "file" and not managed):
        return Check(
            "hook",
            "fail",
            "not installed by kb",
            "move it aside, then run kb setup",
        )
    if kb_problem is not None:
        return Check("hook", "fail", kb_problem, "run kb setup --kb PATH")
    return Check("hook", "pass", "installed by kb setup; its kb runs --version")


def curation_check(findings: Sequence[str]) -> Check:
    """Whether any curation batch is unsettled or committed but not published."""
    if not findings:
        return Check("curation", "pass", "no unsettled batch")
    return Check("curation", "warn", "; ".join(findings), "run the status command named above")


def sync_check(state: SyncState | None, problem: str | None, now: datetime) -> Check:
    """Whether the last regular sync exchanged with origin within the last hour."""
    if problem is not None:
        return Check("sync", "fail", f"record unreadable: {problem}", "run kb sync")
    if state is None:
        return Check("sync", "fail", "No record", "run kb sync")
    if state.last_outcome != "ok":
        detail = f": {state.message}" if state.message else ""
        return Check("sync", "warn", f"last run ended {state.last_outcome}{detail}", "run kb sync")
    if state.last_exchange is None:
        return Check("sync", "warn", "no successful exchange recorded", "run kb sync")
    if now - state.last_exchange > SYNC_MAX_AGE:
        return Check(
            "sync",
            "warn",
            f"last exchange {_stamp(state.last_exchange)}, older than 60 minutes",
            "run kb sync; then check the scheduler",
        )
    return Check("sync", "pass", f"last exchange {_stamp(state.last_exchange)}")


def scheduler_check(
    platform: str, enabled: str | None, active: str | None, problem: str | None
) -> Check:
    """Whether the timer that runs kb sync is enabled and active. Only Linux is checked."""
    if platform != "linux":
        return Check(
            "scheduler", "warn", f"not checked on {platform}", "check the scheduler by hand"
        )
    if problem is not None:
        return Check(
            "scheduler", "warn", f"cannot query systemctl: {problem}", "check the timer by hand"
        )
    if enabled == "enabled" and active == "active":
        return Check("scheduler", "pass", f"{TIMER} is enabled and active")
    return Check(
        "scheduler",
        "warn",
        f"{TIMER} is {enabled or 'unknown'} and {active or 'unknown'}",
        f"enable and start {TIMER} for this user",
    )


def capture_check(
    harvest_set: bool,
    unreadable: Sequence[str],
    old_ready: int | None,
    claude_retention: str,
    codex_retention: str,
    problem: str | None,
) -> Check:
    """Whether capture is enabled, its roots are readable, and no ready transcript is ageing out."""
    if problem is not None:
        return Check("capture", "warn", f"cannot check capture: {problem}", "run kb doctor again")
    if not harvest_set:
        return Check(
            "capture",
            "warn",
            "Capture disabled (harvest_since unset)",
            "run kb setup --enable-capture",
        )
    if unreadable:
        return Check(
            "capture",
            "warn",
            "unreadable transcript root: " + ", ".join(unreadable),
            "make the transcript root readable by this user",
        )
    if old_ready:
        return Check(
            "capture",
            "warn",
            f"{old_ready} ready transcript(s) older than 20 days; Claude Code keeps transcripts "
            f"{claude_retention}; Codex retention is {codex_retention}",
            "run kb sync now, so the transcripts are harvested before the host deletes them",
        )
    return Check(
        "capture",
        "pass",
        "harvest_since set; transcript roots readable; no ready transcript older than 20 days",
    )


def instructions_check(problems: dict[str, str | None]) -> Check:
    """Whether each host's global file contains the canonical instruction block."""
    failed = [f"{host}: {problem}" for host, problem in problems.items() if problem is not None]
    if failed:
        return Check(
            "instructions",
            "warn",
            "; ".join(failed),
            "install the output of kb setup --print instructions in each host's global file",
        )
    return Check("instructions", "pass", "each host's global file has the canonical block")


def skills_check(findings: Sequence[str], foreign: bool = False) -> Check:
    """Whether each host has the packaged skills and the setup command that fixes the findings."""
    if not findings:
        return Check("skills", "pass", "both skills match the package for Claude Code and Codex")
    fix = "move unmanaged skill paths aside, then run kb setup" if foreign else "run kb setup"
    return Check("skills", "warn", "; ".join(findings), fix)


def allow_rules_check(problems: dict[str, Sequence[str]]) -> Check:
    """Whether each host has every working-agent rule and no broader kb rule."""
    failed = [f"{host}: {'; '.join(items)}" for host, items in problems.items() if items]
    if failed:
        return Check(
            "allow-rules",
            "warn",
            " | ".join(failed),
            "install the output of kb setup --print allow-claude or allow-codex in each host",
        )
    return Check(
        "allow-rules", "pass", "each host has every working-agent rule and no other kb rule"
    )


def instruction_problem(text: str | None, canonical: str) -> str | None:
    """What is wrong with a host's global file, or None when it holds the canonical block."""
    if text is None:
        return "no global file"
    lines = text.splitlines()
    begin, end = setup_rules.BEGIN_MARKER, setup_rules.END_MARKER
    if begin not in lines:
        return "no kb block"
    start = lines.index(begin)
    if end not in lines[start + 1 :]:
        return "kb block has no end marker"
    stop = lines.index(end, start)
    block = "\n".join(lines[start : stop + 1]) + "\n"
    return None if block == canonical else "block differs from the canonical block"


def claude_allow_problems(rules: Sequence[str] | None) -> tuple[str, ...]:
    """Missing working-agent rules and broader kb rules in a Claude Code allow list."""
    if rules is None:
        return ("no permissions.allow list",)
    normalized = {_claude_form(rule) for rule in rules}
    problems = [f"missing {rule}" for rule in sorted(EXPECTED_CLAUDE - normalized)]
    problems.extend(
        f"broader {rule}"
        for rule in sorted(normalized)
        if rule.startswith("Bash(kb") and rule not in EXPECTED_CLAUDE
    )
    return tuple(problems)


def codex_allow_problems(text: str | None, linked: Sequence[str] = ()) -> tuple[str, ...]:
    """Missing working-agent prefix rules and broader kb allow rules in Codex rules files.

    text holds the regular rules files that Codex loads. linked names the symlinked rules
    files, which Codex skips.
    """
    skipped = tuple(f"{name} is a symbolic link, which Codex skips" for name in linked)
    if text is None:
        return (*skipped, "no rules files")
    allowed: set[tuple[str, ...]] = set()
    for chunk in text.split("prefix_rule(")[1:]:
        pattern = PATTERN.search(chunk)
        if pattern is None:
            continue
        decision = DECISION.search(chunk)
        if (decision.group(1) if decision else "allow") == "allow":
            allowed.add(tuple(QUOTED.findall(pattern.group(1))))
    problems = [*skipped]
    problems.extend(
        f"missing kb {command}" for command in WORKING if ("kb", command) not in allowed
    )
    problems.extend(
        f"broader {' '.join(tokens)}"
        for tokens in sorted(allowed)
        if tokens[:1] == ("kb",) and tokens not in EXPECTED_CODEX
    )
    return tuple(problems)


def _claude_form(rule: str) -> str:
    """The space form of a Claude Code Bash rule. The colon form is equivalent at the end."""
    return rule[:-3] + " *)" if rule.endswith(":*)") else rule


def _stamp(moment: datetime) -> str:
    """A UTC timestamp in the form the sync record uses."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
