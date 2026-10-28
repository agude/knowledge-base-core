"""kb verify: set an article's verification date and a required valid TTL."""

import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from kb import args, corpus, lint, lock, model, secrets
from kb.args import Spec
from kb.context import Context, load
from kb.errors import KbError
from kb.locators import parse_locator

WHO = "verify"
SPEC = Spec(
    usage="verify ARTICLE [--ttl TTL]",
    summary=(
        "Set an article's verified date to today. A valid ttl is required; use --ttl to set or "
        "replace it. ARTICLE must name one file under knowledge/."
    ),
    valued=frozenset({"--ttl"}),
)


def run(words: Sequence[str]) -> int:
    """Verify one knowledge article and print its path and TTL."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if len(parsed.words) != 1:
        raise SPEC.usage_error()

    ttl_override = parsed.values.get("--ttl")
    if ttl_override is not None and not lint.valid_ttl(ttl_override):
        raise KbError(f"{WHO}: invalid TTL: {ttl_override}")
    wait = _wait()

    try:
        context = load(os.environ, sys.platform, Path.home())
        relpath = _article_path(context.root, parsed.words[0])
        git = lock.git_dir_path(context.root, WHO)
        ttl = _verify(context, relpath, git, ttl_override, wait)
    except lock.LockBusy as busy:
        raise KbError(
            f"{WHO}: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except KbError as error:
        if str(error).startswith((WHO, "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error

    sys.stdout.write(f"Verified: {relpath} (ttl {ttl})\n")
    return 0


def _wait() -> int:
    """The lock wait from KB_LOCK_WAIT. An invalid value is a usage error."""
    try:
        return lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise SPEC.usage_error() from None


def _article_path(root: Path, word: str) -> str:
    """Resolve one whole Markdown file under knowledge/."""
    locator = parse_locator(word)
    if locator.fragment is not None:
        raise KbError(f"{WHO}: ARTICLE must not include a fragment: {word}")
    relpath = corpus.resolve_path(root, locator.path, WHO)
    if relpath is None:
        raise KbError(f'{WHO}: no article matches "{locator.path}"')
    if relpath != "knowledge" and not relpath.startswith("knowledge/"):
        raise KbError(f"{WHO}: ARTICLE must name a file under knowledge/: {relpath}")
    if not relpath.endswith(".md") or not (root / relpath).is_file():
        raise KbError(f"{WHO}: ARTICLE must name a Markdown file: {relpath}")
    return relpath


def _verify(
    context: Context,
    relpath: str,
    git: Path,
    ttl_override: str | None,
    wait: int,
) -> str:
    """Propose, lint, and atomically publish one edit while holding both shared locks."""
    root = context.root
    article = root / relpath
    backend = lock.default_backend(sys.platform)
    with lock.write_lock(git, root, wait, backend):
        try:
            original = article.read_bytes()
            original_text = original.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KbError(f"{WHO}: article is not valid UTF-8: {error.reason}") from error

        bom = "\ufeff" if original_text.startswith("\ufeff") else ""
        text = original_text.removeprefix(bom)
        document = model.parse(relpath, text)
        if not document.front_matter_opened:
            raise KbError(f"{WHO}: unsafe front matter: front matter is missing")
        if not document.front_matter_closed:
            raise KbError(f"{WHO}: unsafe front matter: front matter is unclosed")
        if document.scalar("conflict") == "unresolved":
            raise KbError(f"{WHO}: article has conflict: unresolved")

        local_verified = [
            f"{relpath}#{section.key}"
            for section in document.sections
            if "verified" in section.meta
        ]
        if local_verified:
            listing = ", ".join(local_verified)
            raise KbError(f"{WHO}: section-level verified metadata is present: {listing}")

        _ensure_editable(document, "verified")
        current_ttl = document.scalar("ttl")
        if ttl_override is None:
            if current_ttl is None or not lint.valid_ttl(current_ttl):
                raise KbError(f"{WHO}: article has no valid ttl; supply --ttl")
            ttl = current_ttl
        else:
            ttl = ttl_override

        proposed_text = text
        if document.scalar("verified") != str(context.today):
            proposed_text = _edit(proposed_text, "verified", str(context.today))

        if ttl_override is not None:
            after_verified = model.parse(relpath, proposed_text)
            _ensure_editable(after_verified, "ttl")
            if after_verified.scalar("ttl") != ttl_override:
                proposed_text = _edit(proposed_text, "ttl", ttl_override, after="verified")

        proposed_text_with_bom = bom + proposed_text
        proposed = model.parse(relpath, proposed_text)
        cache = {relpath: proposed}
        findings = lint.check_document(proposed, require_ttl=True)
        findings.extend(lint.reference_findings(root, proposed, cache))
        errors = [finding for finding in findings if finding.severity == "error"]
        if errors:
            details = "\n".join(
                f"  {finding.path}:{finding.line}: {finding.message}" for finding in errors
            )
            raise KbError(f"{WHO}: proposed result has lint errors:\n{details}")

        secret_findings = secrets.findings(Path(tempfile.gettempdir()), ttl)
        if secret_findings:
            detail = ", ".join(f"{name} at line {line}" for name, line in secret_findings)
            raise KbError(f"{WHO}: --ttl was refused by the secrets check: {detail}")

        result = proposed_text_with_bom.encode("utf-8")
        if result == original:
            return ttl

        scratch = git / "kb-tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = scratch / f"verify-{os.urandom(4).hex()}.md"
        try:
            with temporary.open("xb") as handle:
                handle.write(result)
            temporary.chmod(article.stat().st_mode & 0o7777)
            temporary.replace(article)
        finally:
            temporary.unlink(missing_ok=True)
    return ttl


def _ensure_editable(document: model.Document, name: str) -> None:
    """Reject a duplicate or block-list field before deciding whether it needs a change."""
    matches = [field for field in document.front_fields if field.name == name]
    if len(matches) > 1:
        raise KbError(f"{WHO}: unsafe front matter: duplicated field: {name}")
    if matches and matches[0].block:
        raise KbError(f"{WHO}: unsafe front matter: field is a block list: {name}")


def _edit(text: str, name: str, value: str, after: str | None = None) -> str:
    """Run the pure front-matter editor and attach a command-specific refusal reason."""
    try:
        return model.edit_front_matter(text, name, value, after=after)
    except model.FrontMatterEditError as error:
        raise KbError(f"{WHO}: unsafe front matter: {error}") from error
