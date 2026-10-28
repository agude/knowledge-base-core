"""kb setup: set this machine's content path and install the content repository's hook.

Setup writes the config file's content key and the pre-commit hook. It reports each one as
created, installed, updated, unchanged, or refused, and exits 1 when any was refused. A
refusal does not stop the other resource. `kb setup --print` writes the host text that the
dotfiles install. Setup never enables capture and never edits host settings or instructions.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from kb import args, config, lock, setup_rules
from kb.args import Spec
from kb.errors import KbError
from kb.platform import config_file

TMP = "kb-tmp"
SPEC = Spec(
    usage=(
        "setup [--content PATH] [--kb PATH] [--replace-old-hook]\n"
        "       setup --print {instructions|allow-claude|allow-codex}"
    ),
    summary=(
        "Set the content path and install the content repository's pre-commit hook, "
        "or print the host text that the dotfiles install."
    ),
    valued=frozenset({"--content", "--kb", "--print"}),
    switches=frozenset({"--replace-old-hook"}),
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
    """The content path as an absolute path for the policy line. The directory need not exist."""
    override = environ.get("KB_CONTENT", "")
    if override:
        return str(Path(override).expanduser().absolute())
    configured = config.read_content_setting(config_file(environ, sys.platform, Path.home()))
    if configured is None:
        raise KbError(
            'setup: no content path; set KB_CONTENT or add content = "PATH" to the config file'
        )
    return str(configured.absolute())


def _configure(parsed: args.Parsed, environ: Mapping[str, str]) -> int:
    """Set the config and install the hook, report each resource, and return the exit status."""
    configuration = config_file(environ, sys.platform, Path.home())
    failures: list[str] = []
    content = parsed.values.get("--content")
    root = _resolve_root(content, environ, configuration, failures)
    if content is None:
        config_state = "unchanged"
    elif root is None:
        config_state = "refused"
    else:
        config_state = _set_config(configuration, root, failures)
    hook_state, hook = _install(
        root, parsed.values.get("--kb"), "--replace-old-hook" in parsed.switches, environ, failures
    )
    sys.stdout.write(f"Config: {config_state} {configuration}\n")
    sys.stdout.write(f"Hook: {hook_state} {'-' if hook is None else hook}\n")
    for failure in failures:
        sys.stderr.write(f"{failure}\n")
    return 1 if failures else 0


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
    target = configuration.resolve() if configuration.is_symlink() else configuration
    existed = target.exists()
    old = target.read_bytes().decode("utf-8") if existed else ""
    new = setup_rules.set_content(old, content)
    if existed and new == old:
        return "unchanged"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{os.urandom(4).hex()}.tmp"
    try:
        temporary.write_bytes(new.encode("utf-8"))
        if existed:
            shutil.copymode(target, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return "updated" if existed else "created"


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
            action = setup_rules.hook_action(_existing(hook), script, replace_old)
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


def _existing(hook: Path) -> setup_rules.ExistingHook:
    """What occupies the hook path."""
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
