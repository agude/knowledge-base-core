"""kb lint: check article structure and metadata without changing the content repository."""

import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path, PureWindowsPath

from kb import args, corpus, lint
from kb.args import Spec
from kb.context import load
from kb.errors import KbError
from kb.model import Document

WHO = "lint"
DEFAULT_PATH = "knowledge"
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
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
            findings.extend(_reference_findings(context.root, document, document_cache))
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


def _reference_findings(
    root: Path,
    source: Document,
    documents: dict[str, Document],
) -> list[lint.Finding]:
    """Resolve local references and parse each Markdown target at most once."""
    findings: list[lint.Finding] = []
    for reference in lint.references(source):
        path, has_fragment, fragment = reference.destination.partition("#")
        if _external_or_absolute(reference.destination, path):
            continue

        source_file = root / source.path
        if reference.kind == "link":
            target = (source_file.parent / path).resolve() if path else source_file.resolve()
        else:
            target = (root / path).resolve()

        try:
            relpath = target.relative_to(root).as_posix()
        except ValueError:
            message = (
                f"local Markdown link escapes content root: {reference.destination}"
                if reference.kind == "link"
                else f"local source reference escapes content root: {reference.destination}"
            )
            findings.append(_reference_error(reference, message))
            continue

        if not target.is_file():
            message = (
                f"missing local Markdown link target: {reference.destination}"
                if reference.kind == "link"
                else f"missing local source reference: {reference.destination}"
            )
            findings.append(_reference_error(reference, message))
            continue
        if not has_fragment or not fragment or target.suffix != ".md":
            continue

        target_document = documents.get(relpath)
        if target_document is None:
            target_document = corpus.read_document(root, relpath)
            documents[relpath] = target_document
        if not lint.fragment_resolves(target_document, fragment):
            message = (
                f"missing local Markdown link anchor '#{fragment}': {reference.destination}"
                if reference.kind == "link"
                else f"missing source reference anchor '#{fragment}': {reference.destination}"
            )
            findings.append(_reference_error(reference, message))
    return findings


def _external_or_absolute(destination: str, path: str) -> bool:
    """Whether a target is a URL or an absolute path, both outside local linting."""
    return (
        destination.startswith("//")
        or _URI_SCHEME.match(destination) is not None
        or path.startswith("/")
        or PureWindowsPath(path).is_absolute()
    )


def _reference_error(reference: lint.Reference, message: str) -> lint.Finding:
    """Build an error finding at the source reference."""
    return lint.Finding(reference.source_path, reference.line, "error", message)
