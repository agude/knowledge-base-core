"""kb lint: check article structure and metadata without changing the content repository."""

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from kb import args, corpus, lint
from kb.args import Spec
from kb.context import load
from kb.errors import KbError

WHO = "lint"
DEFAULT_PATH = "knowledge"
SPEC = Spec(
    usage="lint [PATH...] [--require-ttl]",
    summary="Check article structure and metadata. PATH is under knowledge/ (default: all of knowledge/).",
    switches=frozenset({"--require-ttl"}),
)


def run(words: Sequence[str]) -> int:
    """Run `kb lint` over one or more article paths."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0

    try:
        context = load(os.environ, sys.platform, Path.home())
        paths = _article_paths(context.root, parsed.words)
        documents = [corpus.read_document(context.root, path) for path in paths]
        document_cache = {document.path: document for document in documents}
        findings = []
        for document in documents:
            findings.extend(lint.check_document(document, "--require-ttl" in parsed.switches))
        for document in documents:
            findings.extend(lint.reference_findings(context.root, document, document_cache))
    except KbError as error:
        if str(error).startswith((WHO, "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error

    findings.sort(
        key=lambda finding: (
            finding.path,
            finding.line,
            0 if finding.severity == "error" else 1,
            finding.message,
        )
    )
    errors = sum(finding.severity == "error" for finding in findings)
    warnings = len(findings) - errors
    lines = [
        f"{finding.path}:{finding.line}: {finding.severity}: {finding.message}"
        for finding in findings
    ]
    lines.append(_summary(errors, warnings, len(documents)))
    sys.stdout.write("\n".join(lines) + "\n")
    return 1 if errors else 0


def _article_paths(root: Path, supplied_paths: Sequence[str]) -> list[str]:
    """Resolve and deduplicate paths, rejecting anything outside knowledge/."""
    if not supplied_paths:
        return corpus.markdown_files(root, DEFAULT_PATH)

    matched_paths: set[str] = set()
    for supplied_path in supplied_paths:
        try:
            relpath = corpus.resolve_path(root, supplied_path, WHO)
        except KbError as error:
            if "resolves outside the content repository" in str(error):
                raise SPEC.usage_error() from error
            raise
        if relpath is None:
            raise KbError(f"{WHO}: no such path: {supplied_path}")
        if relpath != "knowledge" and not relpath.startswith("knowledge/"):
            raise SPEC.usage_error()
        matched_paths.update(corpus.markdown_files(root, relpath))
    return sorted(matched_paths)


def _summary(errors: int, warnings: int, files: int) -> str:
    """The clean summary or the finding totals with singular nouns where needed."""
    if errors == 0 and warnings == 0:
        return f"Lint: 0 errors, 0 warnings in {files} file(s)"
    error_word = "error" if errors == 1 else "errors"
    warning_word = "warning" if warnings == 1 else "warnings"
    return f"Lint: {errors} {error_word}, {warnings} {warning_word} in {files} file(s)"
