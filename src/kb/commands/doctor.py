"""kb doctor: name what is wrong with this machine's kb setup, and the fix for each problem.

Doctor is read only. It takes no lock, sets GIT_OPTIONAL_LOCKS=0 for every Git call, never
fetches, and writes no file. Each check gathers its own facts, so a check that cannot gather
them reports a warning or failure with the reason, and the remaining checks still run. The
rules that judge the facts live in kb.diagnosis.
"""

import json
import os
import platform as python_platform
import re
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kb import (
    __version__,
    args,
    config,
    dates,
    diagnosis,
    observation,
    registrations,
    setup_rules,
    skills,
    sync_state,
)
from kb.args import Spec
from kb.commands import curate, sync
from kb.commands.setup import existing_hook
from kb.diagnosis import Check, State
from kb.errors import KbError
from kb.platform import config_file, scheduler_commands

SPEC = Spec(
    usage="doctor",
    summary="Check this machine's kb setup and name the fix for each problem. Reads only.",
)
TIMEOUT_SECONDS = 30
SCRIPT_COMMAND = re.compile(r"exec '(.+)' hook pre-commit \"\$@\"")


@dataclass(frozen=True)
class Context:
    """What the checks read: the environment, the config file, the home, the platform, the clock."""

    environ: Mapping[str, str]
    configuration: Path
    home: Path
    platform: str
    now: datetime


def run(words: Sequence[str]) -> int:
    """Print one line per check, and return 1 when any check fails."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words or parsed.values or parsed.switches:
        raise SPEC.usage_error()
    environ = os.environ
    home = Path.home()
    context = Context(
        environ=environ,
        configuration=config_file(environ, sys.platform, home),
        home=home,
        platform=sys.platform,
        now=dates.now(environ),
    )
    checks = gather(context)
    for check in checks:
        sys.stdout.write(f"{check.state.upper()} {check.name}: {check.message}\n")
        if check.state != "pass" and check.fix is not None:
            sys.stdout.write(f"  fix: {check.fix}\n")
    return 1 if any(check.state == "fail" for check in checks) else 0


def gather(context: Context) -> list[Check]:
    """Every check, in the order of the plan's table. A check that fails to gather is reported."""
    config_result, root = _config(context)

    def with_root(name: str, state: State, action: Callable[[Path], Check]) -> Check:
        if root is None:
            return Check(name, state, "no content root; see the config check", diagnosis.CONFIG_FIX)
        return _guarded(name, state, lambda: action(root))

    return [
        diagnosis.version_check(__version__, python_platform.python_version()),
        config_result,
        with_root("content", "fail", _content),
        with_root("gitattributes", "warn", _gitattributes),
        with_root("hook", "fail", _hook),
        with_root(
            "curation",
            "warn",
            lambda found: diagnosis.curation_check(curate.doctor_findings(found)),
        ),
        with_root("sync", "warn", lambda found: _sync(found, context)),
        _guarded("scheduler", "warn", lambda: _scheduler(context)),
        _guarded("capture", "warn", lambda: _capture(context, root)),
        _guarded("instructions", "warn", lambda: _instructions(context, root)),
        _guarded("skills", "warn", lambda: _skills(context)),
        _guarded("allow-rules", "warn", lambda: _allow_rules(context)),
        _guarded("legacy", "warn", lambda: _legacy(context, root)),
    ]


def _guarded(name: str, state: State, action: Callable[[], Check]) -> Check:
    """The check's result, or a state and the reason when its facts cannot be gathered."""
    try:
        return action()
    except (KbError, OSError, UnicodeError, subprocess.SubprocessError) as error:
        return Check(
            name, state, f"cannot check: {error}", "fix the cause, then run kb doctor again"
        )


def _config(context: Context) -> tuple[Check, Path | None]:
    """The content root and where its setting comes from."""
    source = "KB_CONTENT" if context.environ.get("KB_CONTENT") else str(context.configuration)
    try:
        root = config.content_root(context.environ, context.configuration)
    except KbError as error:
        return diagnosis.config_check(source, None, str(error)), None
    return diagnosis.config_check(source, str(root), None), root


def _content(root: Path) -> Check:
    """The Git state of the content root: repository, branch, origin, worktree, and origin."""
    top = _git(root, "rev-parse", "--show-toplevel")
    repo = top.returncode == 0 and Path(top.stdout.strip()).resolve() == root.resolve()
    if not repo:
        return diagnosis.content_check(False, None, False, 0, False, None, None)
    branch_result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    origin = _git(root, "remote", "get-url", "origin").returncode == 0
    dirty = _dirty_count(root)
    fetched, ahead, behind = False, None, None
    if branch is not None:
        remote_ref = f"refs/remotes/origin/{branch}"
        if _git(root, "show-ref", "--verify", "--quiet", remote_ref).returncode == 0:
            counts = _git(root, "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}")
            values = counts.stdout.split()
            if counts.returncode == 0 and len(values) == 2 and all(v.isdigit() for v in values):
                fetched = True
                ahead, behind = int(values[0]), int(values[1])
    return diagnosis.content_check(True, branch, origin, dirty, fetched, ahead, behind)


def _dirty_count(root: Path) -> int:
    """The changed or untracked paths in the worktree, not counting the old observer lock."""
    result = _git(root, "status", "--porcelain", "--untracked-files=all")
    if result.returncode != 0:
        raise KbError(f"cannot inspect working tree: {result.stderr.rstrip()}")
    paths = [line[3:] for line in result.stdout.splitlines()]
    return sum(
        1 for path in paths if path != ".observe.lock" and not path.startswith(".observe.lock/")
    )


def _gitattributes(root: Path) -> Check:
    """The text and eol attributes that Git resolves for a path in the content root."""
    result = _git(root, "check-attr", "text", "eol", "--", "probe.md")
    if result.returncode != 0:
        raise KbError(f"cannot read attributes: {result.stderr.rstrip()}")
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split(": ", 2)
        if len(parts) == 3:
            values[parts[1]] = parts[2]
    return diagnosis.gitattributes_check(
        values.get("text", "unspecified"), values.get("eol", "unspecified")
    )


def _hook(root: Path) -> Check:
    """The pre-commit hook at Git's hooks path: its kind, whether it is kb's, and its kb."""
    result = _git(root, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    if result.returncode != 0:
        raise KbError(f"cannot locate the hooks directory: {result.stderr.rstrip()}")
    hook = Path(result.stdout.strip()) / "pre-commit"
    found = existing_hook(hook)
    old_link = found.kind == "link" and setup_rules.is_old_hook_target(found.link_target)
    managed = found.kind == "file" and setup_rules.is_managed(found.data)
    problem = _kb_problem(found.data) if managed else None
    return diagnosis.hook_check(found.kind, old_link, managed, problem)


def _kb_problem(script: bytes) -> str | None:
    """Whether the kb that a managed hook names exists and prints a kb version, or the problem."""
    lines = script.decode("utf-8", errors="replace").splitlines()
    match = SCRIPT_COMMAND.fullmatch(lines[2]) if len(lines) > 2 else None
    if match is None:
        return "managed hook names no kb path"
    path = Path(match.group(1))
    if not path.exists():
        return f"kb path is missing: {path}"
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return f"kb path does not run: {path}"
    if result.returncode != 0 or not setup_rules.version_line_ok(result.stdout):
        return f"kb path does not print a kb version: {path}"
    return None


def _sync(root: Path, context: Context) -> Check:
    """The sync outcome record in the common Git directory."""
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common.returncode != 0:
        raise KbError(f"cannot locate the Git directory: {common.stderr.rstrip()}")
    try:
        state = sync_state.read(Path(common.stdout.strip()))
    except KbError as error:
        return diagnosis.sync_check(None, str(error), context.now)
    return diagnosis.sync_check(state, None, context.now)


def _scheduler(context: Context) -> Check:
    """Whether the user's timer that runs kb sync is enabled and active, where kb checks it."""
    commands = scheduler_commands(context.platform)
    if commands is None:
        return diagnosis.scheduler_check(context.platform, None, None, None)
    enabled_command, active_command = commands
    try:
        enabled = _stdout(enabled_command)
        active = _stdout(active_command)
    except (OSError, subprocess.SubprocessError) as error:
        return diagnosis.scheduler_check(context.platform, None, None, str(error))
    return diagnosis.scheduler_check(context.platform, enabled, active, None)


def _capture(context: Context, root: Path | None) -> Check:
    """Whether harvesting is enabled, the transcript roots are readable, and no transcript ages out."""
    harvest_since = config.read_harvest_since(context.configuration)
    claude_store = _store(context.environ, "CLAUDE_CONFIG_DIR", context.home / ".claude")
    codex_store = _store(context.environ, "CODEX_HOME", context.home / ".codex")
    roots = (claude_store / "projects", codex_store / "sessions")
    unreadable = [
        str(path) for path in roots if path.exists() and not os.access(path, os.R_OK | os.X_OK)
    ]
    old_ready: int | None = None
    problem: str | None = None
    if harvest_since is not None:
        if root is None:
            problem = "no content root to read HEAD from"
        else:
            try:
                found = sync.backlog(
                    root,
                    context.environ,
                    observation.short_host(socket.gethostname()),
                    context.now,
                    harvest_since,
                )
            except KbError as error:
                problem = str(error)
            else:
                cutoff = context.now - diagnosis.TRANSCRIPT_MAX_AGE
                old_ready = sum(
                    1 for modified in found.selection.ready_modified if modified < cutoff
                )
    return diagnosis.capture_check(
        harvest_since is not None,
        unreadable,
        old_ready,
        _claude_retention(claude_store),
        "unknown",
        problem,
    )


def _claude_retention(store: Path) -> str:
    """How long Claude Code keeps transcripts: its cleanupPeriodDays setting, or the default."""
    days = _json_object(store / "settings.json").get("cleanupPeriodDays")
    if type(days) is int:
        return f"for {days} days (cleanupPeriodDays)"
    return "for 30 days (default)"


def _instructions(context: Context, root: Path | None) -> Check:
    """Whether each host's global file contains the canonical block for this content root."""
    if root is None:
        raise KbError("no content root, so the canonical block cannot be rendered")
    canonical = setup_rules.instruction_block(str(root))
    claude_file = (
        _store(context.environ, "CLAUDE_CONFIG_DIR", context.home / ".claude") / "CLAUDE.md"
    )
    codex_file = _store(context.environ, "CODEX_HOME", context.home / ".codex") / "AGENTS.md"
    return diagnosis.instructions_check(
        {
            "claude": diagnosis.instruction_problem(_read_text(claude_file), canonical),
            "codex": diagnosis.instruction_problem(_read_text(codex_file), canonical),
        }
    )


def _skills(context: Context) -> Check:
    """Whether Claude Code and Codex have both packaged skills installed and unchanged."""
    claude_store = _store(context.environ, "CLAUDE_CONFIG_DIR", context.home / ".claude")
    hosts = (
        ("Claude Code", claude_store / "skills"),
        ("Codex", context.home / ".agents" / "skills"),
    )
    old_root = Path(
        context.environ.get("KNOWLEDGE_BASE") or context.home / "Knowledge"
    ).expanduser()
    findings = []
    old_link = False
    foreign = False
    descriptions = {
        skills.SkillAction.INSTALL: "is missing",
        skills.SkillAction.UPDATE: "differs from the package",
        skills.SkillAction.REFUSE_OLD_LINK: "links into old tooling",
        skills.SkillAction.REFUSE_FOREIGN: "is unmanaged",
        skills.SkillAction.UNCHANGED: "is unchanged",
    }
    for host, directory in hosts:
        for name in skills.SKILL_NAMES:
            action = skills.classify(directory / name, skills.package_files(name), old_root)
            if action is skills.SkillAction.UNCHANGED:
                continue
            findings.append(f"{host} {name} {descriptions[action]}")
            old_link = old_link or action is skills.SkillAction.REFUSE_OLD_LINK
            foreign = foreign or action is skills.SkillAction.REFUSE_FOREIGN
    return diagnosis.skills_check(tuple(findings), old_link, foreign)


def _allow_rules(context: Context) -> Check:
    """Whether each host approves every working-agent command and no broader kb command."""
    claude_store = _store(context.environ, "CLAUDE_CONFIG_DIR", context.home / ".claude")
    codex_store = _store(context.environ, "CODEX_HOME", context.home / ".codex")
    return diagnosis.allow_rules_check(
        {
            "claude": diagnosis.claude_allow_problems(
                _claude_allow(claude_store / "settings.json")
            ),
            "codex": diagnosis.codex_allow_problems(_codex_rules(codex_store / "rules")),
        }
    )


def _legacy(context: Context, root: Path | None) -> Check:
    """The old tooling's registrations: coat-tree links, hook entries, old hooks, and skill links."""
    findings: list[str] = []
    findings.extend(_coat_tree_findings(context))
    claude_store = _store(context.environ, "CLAUDE_CONFIG_DIR", context.home / ".claude")
    findings.extend(_claude_hook_findings(claude_store / "settings.json"))
    codex_store = _store(context.environ, "CODEX_HOME", context.home / ".codex")
    findings.extend(_codex_hook_findings(codex_store / "hooks.json"))
    if root is not None:
        findings.extend(_content_hook_findings(root))
    old_root = Path(
        context.environ.get("KNOWLEDGE_BASE") or context.home / "Knowledge"
    ).expanduser()
    findings.extend(_skill_findings(claude_store / "skills", old_root))
    findings.extend(_skill_findings(context.home / ".agents" / "skills", old_root))
    return diagnosis.legacy_check(tuple(findings))


def _coat_tree_findings(context: Context) -> list[str]:
    """Each coat-tree hook entry that the old tooling installed, named with its target."""
    config_home = Path(context.environ.get("XDG_CONFIG_HOME") or context.home / ".config")
    return registrations.coat_tree_findings(config_home)


def _claude_hook_findings(settings: Path) -> list[str]:
    """Claude Code hook commands that mention the knowledge base."""
    data = _json_object(settings)
    findings = []
    for event, command in _hook_commands(data.get("hooks", {})):
        if re.search("knowledge", command, re.IGNORECASE):
            findings.append(f"Claude settings {event} hook: {command}")
    return findings


def _codex_hook_findings(hooks_file: Path) -> list[str]:
    """Codex hook scripts whose text mentions the knowledge base."""
    return registrations.codex_hook_findings(hooks_file)


def _content_hook_findings(root: Path) -> list[str]:
    """A content pre-commit hook that is a link into the old tooling."""
    hooks = _git(root, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    if hooks.returncode != 0:
        return []
    hook = Path(hooks.stdout.strip()) / "pre-commit"
    if not hook.is_symlink() or not setup_rules.is_old_hook_target(str(hook.readlink())):
        return []
    return [f"content pre-commit link -> {hook.readlink()}"]


def _skill_findings(directory: Path, old_root: Path) -> list[str]:
    """Skill links whose targets lie inside the old tooling's checkout."""
    if not directory.is_dir():
        return []
    findings = []
    for link in sorted(directory.iterdir()):
        if link.is_symlink() and link.resolve().is_relative_to(old_root.resolve()):
            findings.append(f"skill link {link} -> {link.resolve()}")
    return findings


def _hook_commands(hooks: object) -> list[tuple[str, str]]:
    """Each (event, command) pair in a host's hooks mapping, tolerating unexpected shapes."""
    return registrations.hook_commands(hooks)


def _claude_allow(settings: Path) -> list[str] | None:
    """The permissions.allow list of a Claude Code settings file, or None when it has none."""
    data = _json_object(settings)
    permissions = data.get("permissions")
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    if not isinstance(allow, list):
        return None
    return [rule for rule in allow if isinstance(rule, str)]


def _codex_rules(directory: Path) -> str | None:
    """The text of every Codex rules file in a directory, or None when there is none."""
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*.rules"))
    if not files:
        return None
    return "\n".join(_read_text(path) or "" for path in files)


def _json_object(path: Path) -> dict[str, object]:
    """A JSON object from a file, or an empty object when the file is absent."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise KbError(f"cannot read {path}: {error}") from error
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str | None:
    """A file's text, or None when it is absent or cannot be read as UTF-8."""
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _store(environ: Mapping[str, str], name: str, default: Path) -> Path:
    """A host store root: the directory named in the environment, or the default."""
    value = environ.get(name, "")
    return Path(value).expanduser() if value else default


def _git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
    """Run one Git command in root without optional locks. Doctor never writes."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _stdout(command: Sequence[str]) -> str:
    """The stripped standard output of a command. Its exit status is not an error here."""
    result = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=TIMEOUT_SECONDS,
    )
    return result.stdout.strip()
