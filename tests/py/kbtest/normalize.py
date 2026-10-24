"""Replace values that vary between runs with stable placeholders.

Every rule is listed in tests/py/README.md. Add a rule there when adding one
here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Observation file names are contract: UTC timestamp, a hyphen, 8 lowercase
# hex digits (observe:94-99).
OBSERVATION_NAME = re.compile(r"\b\d{8}T\d{6}-[0-9a-f]{8}\.md\b")
# Anything shaped like an observation name. Used to reject near misses before
# the contract pattern replaces the exact ones.
OBSERVATION_LIKE = re.compile(r"\b\d{8}T\d{6}-[^\s/\"']*\.md\b")

CREATED = re.compile(r"^(created: )\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", re.MULTILINE)
# Integer from the jq-free encoder, float from jq.
BUFFER_TIMESTAMP = re.compile(r'("timestamp":)\d+(?:\.\d+)?')
# Messages printed by git and jq. Their wording changes between tool versions.
TOOL_MESSAGE = re.compile(r"^(fatal|error|warning|hint): .*$", re.MULTILINE)
JQ_MESSAGE = re.compile(r"^jq: .*$", re.MULTILINE)


class NormalizationError(AssertionError):
    """Output violates a contract the normalizer depends on."""


@dataclass
class Normalizer:
    """Normalize output from one test.

    paths: literal paths to replace, longest first, mapped to placeholders.
    commits: full commit hashes known to the test; any prefix of 7 or more
    hex digits is replaced.
    extra: further literal replacements, such as pids.
    """

    paths: dict[Path, str] = field(default_factory=dict)
    commits: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)
    _observations: dict[str, str] = field(default_factory=dict)
    _commit_labels: dict[str, str] = field(default_factory=dict)

    def add_path(self, path: Path, placeholder: str) -> None:
        self.paths[path] = placeholder
        resolved = path.resolve()
        if resolved != path:
            self.paths[resolved] = placeholder

    def __call__(self, text: str) -> str:
        text = self._replace_paths(text)
        text = self._replace_observations(text)
        text = CREATED.sub(r"\1<TIMESTAMP>", text)
        text = BUFFER_TIMESTAMP.sub(r"\1<EPOCH>", text)
        text = self._replace_commits(text)
        for literal, placeholder in self.extra.items():
            text = text.replace(literal, placeholder)
        return text

    def stderr(self, text: str) -> str:
        """Normalize stderr, which also carries git and jq messages."""
        text = self(text)
        text = TOOL_MESSAGE.sub(lambda m: f"<git {m.group(1)}>", text)
        return JQ_MESSAGE.sub("<jq message>", text)

    def _replace_paths(self, text: str) -> str:
        for path in sorted(self.paths, key=lambda p: len(str(p)), reverse=True):
            text = text.replace(str(path), self.paths[path])
        return text

    def _replace_observations(self, text: str) -> str:
        for match in OBSERVATION_LIKE.finditer(text):
            if not OBSERVATION_NAME.fullmatch(match.group(0)):
                raise NormalizationError(
                    f"observation file name {match.group(0)!r} does not match "
                    "YYYYMMDDTHHMMSS-<8 lowercase hex>.md"
                )

        def label(match: re.Match[str]) -> str:
            name = match.group(0)
            if name not in self._observations:
                self._observations[name] = f"<OBS-{len(self._observations) + 1}>.md"
            return self._observations[name]

        return OBSERVATION_NAME.sub(label, text)

    def _replace_commits(self, text: str) -> str:
        if not self.commits:
            return text

        def label(match: re.Match[str]) -> str:
            token = match.group(0)
            for full in self.commits:
                if full.startswith(token):
                    if full not in self._commit_labels:
                        self._commit_labels[full] = f"<COMMIT-{len(self._commit_labels) + 1}>"
                    return self._commit_labels[full]
            return token

        return re.sub(r"\b[0-9a-f]{7,40}\b", label, text)


def report(text: str) -> str:
    """Normalize an evaluate-retrieval JSON report and return it indented."""

    def walk(value: object) -> object:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if "latency_ms" in key:
                    result[key] = "<MS>"
                elif key == "measured_at":
                    result[key] = "<TIMESTAMP>"
                elif key == "latency_clock":
                    result[key] = "<CLOCK>"
                else:
                    result[key] = walk(item)
            return result
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return json.dumps(walk(json.loads(text)), indent=2, ensure_ascii=False) + "\n"
