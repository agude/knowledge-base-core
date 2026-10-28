"""kb setup: configure this machine's content path, hooks, and transcript cutoff.

Setup writes the config file's content key, installs the pre-commit hook, and can enable
transcript capture. It reports each resource as created, installed, updated, unchanged, or
refused, and exits 1 when any was refused. A refusal does not stop the other resource.
`kb setup --print` writes the host text that the dotfiles install. `--enable-capture` sets the
transcript cutoff after the other setup work; it does not edit host settings or instructions.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC
from pathlib import Path

from kb import args, config, dates, lock, registrations, setup_rules
from kb.args import Spec
from kb.errors import KbError
from kb.platform import config_file

TMP = "kb-tmp"
LAYOUT = (
    "knowledge",
    "sources",
    "observations/pending",
    "observations/archived",
    "observations/batches",
    "questions/open",
    "questions/resolved",
)
GITATTRIBUTES = "* text=auto eol=lf\n"
POLICY_STUB = (
    "This file holds the content repository's rules for agents. Agents that read or change "
    "this repository follow the rules in this file.\n"
)
INITIAL_COMMIT = "Initialize knowledge base content"
SPEC = Spec(
    usage=(
        "setup [--content PATH | --init PATH [--origin URL]] [--kb PATH] "
        "[--replace-old-hook] [--enable-capture]\n"
        "       setup --print {instructions|allow-claude|allow-codex}"
    ),
    summary=(
        "Set the content path and install the content repository's pre-commit hook, "
        "create a content repository with --init, enable transcript capture, or print the host "
        "text that the dotfiles install."
    ),
    valued=frozenset({"--content", "--init", "--origin", "--kb", "--print"}),
    switches=frozenset({"--replace-old-hook", "--enable-capture"}),
)


def run(words: Sequence[str]) -> int:
    """Configure the machine, or print host text with --print, and return the exit status."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words:
        raise SPEC.usage_error()
    if "--print" in parsed.values:
        if set(parsed.values) != {"--print"} or parsed.switches:
            raise SPEC.usage_error()
        sys.stdout.write(_render(parsed.values["--print"], os.environ))
        return 0
    if "--init" in parsed.values and "--content" in parsed.values:
        raise SPEC.usage_error()
    if "--origin" in parsed.values and "--init" not in parsed.values:
        raise SPEC.usage_error()
    return _configure(parsed, os.environ)


def _render(item: str, environ: Mapping[str, str]) -> str:
    """The text for one --print item."""
    if item == "allow-claude":
        return setup_rules.allow_claude()
    if item == "allow-codex":
        return setup_rules.allow_codex()
    if item == "instructions":
        try:
            return setup_rules.instruction_block(_print_root(environ))
        except KbError as error:
            raise KbError(_labelled(str(error))) from None
    raise KbError(f"setup: --print takes {', '.join(setup_rules.ITEMS)}; not {item}")


def _print_root(environ: Mapping[str, str]) -> str:
    """The content path for the policy line, resolved as config.content_root resolves it.

    Doctor renders the canonical block from the resolved root, so the printed block must use
    the same form of the path. The directory need not exist.
    """
    override = environ.get("KB_CONTENT", "")
    if override:
        return str(Path(override).expanduser().resolve())
    configured = config.read_content_setting(config_file(environ, sys.platform, Path.home()))
    if configured is None:
        raise KbError(
            'setup: no content path; set KB_CONTENT or add content = "PATH" to the config file'
        )
    return str(configured.resolve())


def _configure(parsed: args.Parsed, environ: Mapping[str, str]) -> int:
    """Set the config and install the hook, report each resource, and return the exit status."""
    configuration = config_file(environ, sys.platform, Path.home())
    failures: list[str] = []
    kb_argument = parsed.values.get("--kb")
    init_argument = parsed.values.get("--init")
    init_state: str | None = None
    init_target: Path | None = None
    if init_argument is not None:
        init_target = Path(init_argument).expanduser().absolute()
        init_state, hook_state, hook, root = _initialize(
            init_target, parsed.values.get("--origin"), kb_argument, environ, failures
        )
        config_state = "refused" if root is None else _set_config(configuration, root, failures)
    else:
        content = parsed.values.get("--content")
        root = _resolve_root(content, environ, configuration, failures)
        if content is None:
            config_state = "unchanged"
        elif root is None:
            config_state = "refused"
        else:
            config_state = _set_config(configuration, root, failures)
        hook_state, hook = _install(
            root, kb_argument, "--replace-old-hook" in parsed.switches, environ, failures
        )
    if init_state is not None:
        sys.stdout.write(f"Init: {init_state} {init_target}\n")
    sys.stdout.write(f"Config: {config_state} {configuration}\n")
    sys.stdout.write(f"Hook: {hook_state} {'-' if hook is None else hook}\n")
    if "--enable-capture" in parsed.switches:
        capture_state, cutoff = _enable_capture(configuration, environ, failures)
        sys.stdout.write(f"Capture: {capture_state} {cutoff}\n")
    for failure in failures:
        sys.stderr.write(f"{failure}\n")
    return 1 if failures else 0


def _initialize(
    target: Path,
    origin: str | None,
    kb_argument: str | None,
    environ: Mapping[str, str],
    failures: list[str],
) -> tuple[str, str, Path | None, Path | None]:
    """Create a content repository, install its hook, make its initial commit, and publish it.

    Returns the init state, the hook state, the hook path, and the repository root, which is
    None when init was refused. A refusal before the initial commit removes what init created,
    so the path is as it was and init can run again. A push failure keeps the local repository
    and reports the recovery commands.
    """
    try:
        _check_empty(target)
        _kb_path(kb_argument)
    except KbError as error:
        failures.append(_labelled(str(error)))
        return "refused", "refused", None, None
    existed = target.exists()
    hook_state, hook = "refused", None
    try:
        _create_layout(target)
        _git_ok(target, "init", "-q", "-b", "main")
        hook_state, hook = _install(target, kb_argument, False, environ, failures)
        if hook_state == "refused":
            raise _Abandoned
        _initial_commit(target, environ)
    except _Abandoned:
        _roll_back(target, existed, failures)
        return "refused", hook_state, hook, None
    except lock.LockBusy as busy:
        failures.append(f"setup: content repository is busy (waited {busy.waited}s for the lock)")
        _roll_back(target, existed, failures)
        return "refused", hook_state, hook, None
    except (KbError, OSError, UnicodeError) as error:
        failures.append(_labelled(str(error)))
        _roll_back(target, existed, failures)
        return "refused", hook_state, hook, None
    if origin is not None:
        _publish(target, origin, failures)
    return "created", hook_state, hook, target


class _Abandoned(Exception):
    """Init stops after a refusal that is already recorded, and removes what it created."""


def _roll_back(target: Path, existed: bool, failures: list[str]) -> None:
    """Remove what init created under target, which was absent or an empty directory.

    A hook installed outside target, through core.hooksPath, is left in place.
    """
    try:
        if existed:
            for child in target.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        else:
            shutil.rmtree(target)
    except OSError as error:
        failures.append(f"setup: cannot remove the partial repository at {target}: {error}")
        return
    failures.append(f"setup: removed the partial repository at {target}")


def _check_empty(target: Path) -> None:
    """Refuse a path that exists and is not an empty directory."""
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise KbError(f"{target} exists and is not an empty directory")


def _create_layout(target: Path) -> None:
    """Create the content layout, each empty directory with a .gitkeep, and the two files."""
    for relative in LAYOUT:
        directory = target / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".gitkeep").touch()
    (target / ".gitattributes").write_bytes(GITATTRIBUTES.encode("utf-8"))
    (target / "AGENTS.md").write_bytes(POLICY_STUB.encode("utf-8"))


def _initial_commit(target: Path, environ: Mapping[str, str]) -> None:
    """Stage everything and commit once, under the writer lock, so the installed hook runs."""
    git = lock.git_dir(target, "setup")
    with lock.write_lock(git, target, _wait(environ), lock.default_backend(sys.platform)):
        _git_ok(target, "add", "--all")
        _git_ok(target, "commit", "-q", "-m", INITIAL_COMMIT)


def _publish(target: Path, origin: str, failures: list[str]) -> None:
    """Add origin and push main. A failure keeps the local repository and names the recovery.

    kb sync cannot finish the first push, because it fetches origin's branch first, so the
    recovery is the Git commands that setup did not complete.
    """
    push = "git push --set-upstream origin main"
    try:
        _git_ok(target, "remote", "add", "origin", origin)
    except KbError as error:
        failures.append(_labelled(str(error)))
        failures.append(
            f"setup: the local repository is kept. In {target}, run: "
            f"git remote add origin URL, then {push}"
        )
        return
    try:
        _git_ok(target, "push", "-q", "--set-upstream", "origin", "main")
    except KbError as error:
        failures.append(_labelled(str(error)))
        failures.append(
            f"setup: the local repository is kept. After fixing origin, in {target}, run: {push}"
        )


def _git_ok(root: Path, *words: str) -> None:
    """Run one git command in root, or raise KbError with its error output."""
    result = subprocess.run(
        ["git", *words],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.rstrip("\n")
        raise KbError(f"git {words[0]} failed: {detail}")


def _resolve_root(
    content: str | None, environ: Mapping[str, str], configuration: Path, failures: list[str]
) -> Path | None:
    """The content root that setup acts on: --content, else the configured one, or None."""
    try:
        if content is not None:
            return _directory(content)
        return config.content_root(environ, configuration)
    except KbError as error:
        failures.append(_labelled(str(error)))
        return None


def _directory(value: str) -> Path:
    """The absolute path of a directory, or KbError."""
    path = Path(value).expanduser().absolute()
    if not path.is_dir():
        raise KbError(f"the content path is not a directory: {path}")
    return path


def _set_config(configuration: Path, root: Path, failures: list[str]) -> str:
    """Write the content key and return the state, or refused with its reason recorded."""
    try:
        return _write_config(configuration, str(root))
    except (KbError, OSError, UnicodeError) as error:
        failures.append(f"setup: {configuration}: {error}")
        return "refused"


def _write_config(configuration: Path, content: str) -> str:
    """Replace the config file atomically with its content key set. Returns the state.

    A symbolic link is followed, so the link itself survives and its target is replaced.
    """
    state, _ = config.write_config(configuration, lambda old: setup_rules.set_content(old, content))
    return state


def _enable_capture(
    configuration: Path, environ: Mapping[str, str], failures: list[str]
) -> tuple[str, str]:
    """Set the transcript cutoff only after every old capture registration is removed."""
    home = Path.home()
    config_home = Path(environ.get("XDG_CONFIG_HOME") or home / ".config").expanduser()
    codex_home = Path(environ.get("CODEX_HOME") or home / ".codex").expanduser()
    try:
        findings = registrations.capture_findings(config_home, codex_home)
    except (KbError, OSError, UnicodeError) as error:
        failures.append(f"setup: cannot check old capture registrations: {error}")
        return "refused", str(configuration)
    if findings:
        failures.extend(
            f"setup: remove the old capture registration before enabling capture: {finding}"
            for finding in findings
        )
        return "refused", str(configuration)
    try:
        now = dates.now(environ).replace(microsecond=0)
        state, text = config.write_config(
            configuration,
            lambda old: config.set_harvest_since(old, now, configuration),
        )
        cutoff = config.parse_harvest_since(text, configuration)
        if cutoff is None:
            raise KbError("harvest_since was not written")
    except (KbError, OSError, UnicodeError) as error:
        failures.append(f"setup: {configuration}: {error}")
        return "refused", str(configuration)
    value = cutoff.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return ("unchanged" if state == "unchanged" else "enabled"), value


def _install(
    root: Path | None,
    kb_argument: str | None,
    replace_old: bool,
    environ: Mapping[str, str],
    failures: list[str],
) -> tuple[str, Path | None]:
    """Install or update the hook under the writer lock. Returns its state and its path."""
    if root is None:
        return "refused", None
    hook: Path | None = None
    try:
        kb_path = _kb_path(kb_argument)
        git = lock.git_dir(root, "setup")
        hook = _hook_file(root)
        script = setup_rules.hook_script(kb_path)
        wait = _wait(environ)
        with lock.write_lock(git, root, wait, lock.default_backend(sys.platform)):
            action = setup_rules.hook_action(existing_hook(hook), script, replace_old)
            return _apply(action, hook, script, git), hook
    except lock.LockBusy as busy:
        failures.append(f"setup: content repository is busy (waited {busy.waited}s for the lock)")
    except (KbError, OSError, UnicodeError) as error:
        failures.append(_labelled(str(error)))
    return "refused", hook


def _kb_path(given: str | None) -> str:
    """The absolute path of the kb executable that the hook calls, after checking that it is kb."""
    if given is not None:
        candidate = Path(given).expanduser()
    else:
        found = shutil.which("kb")
        if found is None:
            raise KbError("kb is not on PATH; pass --kb PATH")
        candidate = Path(found)
    path = str(candidate.absolute())
    setup_rules.check_hook_path(path)
    _check_version(path)
    return path


def _check_version(path: str) -> None:
    """Require the executable to print `kb` followed by a version for --version."""
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise KbError(f"{path} does not run: {error}") from None
    if result.returncode != 0 or not setup_rules.version_line_ok(result.stdout):
        raise KbError(f"{path} is not a kb executable: --version did not print kb and a version")


def _hook_file(root: Path) -> Path:
    """The pre-commit hook path that Git uses for the repository, which honors core.hooksPath."""
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", "hooks"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise KbError(f"cannot locate the hooks directory of {root}")
    return Path(result.stdout.removesuffix("\n")) / "pre-commit"


def existing_hook(hook: Path) -> setup_rules.ExistingHook:
    """What occupies the hook path: nothing, a symbolic link, a regular file, or another kind."""
    if hook.is_symlink():
        return setup_rules.ExistingHook("link", link_target=str(hook.readlink()))
    if hook.is_file():
        return setup_rules.ExistingHook("file", data=hook.read_bytes())
    if hook.exists():
        return setup_rules.ExistingHook("other")
    return setup_rules.ExistingHook("absent")


def _apply(action: setup_rules.HookAction, hook: Path, script: str, git: Path) -> str:
    """Carry out a hook action and return its state. Refusals raise KbError."""
    if action is setup_rules.HookAction.UNCHANGED:
        return "unchanged"
    if action is setup_rules.HookAction.REFUSE_OLD_LINK:
        raise KbError(
            f"{hook} is a symlink to the old tooling's hook; run again with --replace-old-hook "
            "to replace the link. Its target is not changed."
        )
    if action is setup_rules.HookAction.REFUSE_FOREIGN:
        raise KbError(
            f"{hook} exists and kb did not install it; it is unchanged. "
            "Move it aside, then run setup again."
        )
    _write_hook(hook, script, git)
    return "installed" if action is setup_rules.HookAction.INSTALL else "updated"


def _write_hook(hook: Path, script: str, git: Path) -> None:
    """Write the script through the Git directory's kb-tmp with mode 0755, then replace the hook.

    The replacement is a rename, so a symbolic link at the hook path is replaced and its
    target is left unchanged.
    """
    scratch = git / TMP
    scratch.mkdir(parents=True, exist_ok=True)
    hook.parent.mkdir(parents=True, exist_ok=True)
    temporary = scratch / f"pre-commit-{os.urandom(4).hex()}"
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(script)
        temporary.chmod(0o755)
        temporary.replace(hook)
    finally:
        temporary.unlink(missing_ok=True)


def _wait(environ: Mapping[str, str]) -> int:
    """KB_LOCK_WAIT in seconds, or KbError."""
    try:
        return lock.parse_wait(environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise KbError("KB_LOCK_WAIT must be a non-negative integer") from None


def _labelled(text: str) -> str:
    """The text with the setup label, which every refusal carries."""
    return text if text.startswith("setup:") else f"setup: {text}"
