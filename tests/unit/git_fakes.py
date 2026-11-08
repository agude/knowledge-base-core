"""Replace kb.git calls whose words match, and run every other call for real."""

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kb import git

Result = subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes] | BaseException
Responder = Callable[[Path, tuple[str, ...]], Result | None]


@dataclass
class FakeGit:
    """Responders run in order; the first non-None result wins. Calls are recorded."""

    real_run: Callable[..., subprocess.CompletedProcess[str]]
    real_run_bytes: Callable[..., subprocess.CompletedProcess[bytes]]
    responders: list[Responder] = field(default_factory=list)
    text_responders: list[Responder] = field(default_factory=list)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    keywords: list[dict[str, Any]] = field(default_factory=list)

    def on(self, prefix: Sequence[str], result: Result, *, times: int | None = None) -> None:
        """Answer calls whose words start with prefix, optionally only the first `times` calls."""
        expected = tuple(prefix)
        remaining = [times]

        def respond(root: Path, words: tuple[str, ...]) -> Result | None:
            if words[: len(expected)] != expected:
                return None
            if remaining[0] is not None:
                if remaining[0] <= 0:
                    return None
                remaining[0] -= 1
            return result

        self.responders.append(respond)

    def wrap(self, function: Callable[..., subprocess.CompletedProcess[Any]]) -> None:
        """Answer every kb.git.run call with function(root, *words); it may call real_run.

        kb.git.run_bytes calls skip it, because a text result would lose their exact bytes.
        """
        self.text_responders.append(lambda root, words: function(root, *words))

    def answer(
        self, root: Path, words: tuple[str, ...], keywords: dict[str, Any], *, text: bool
    ) -> subprocess.CompletedProcess[Any] | None:
        """Record the call and return the first responder result, or None to run real Git."""
        self.calls.append(words)
        self.keywords.append(keywords)
        for responder in [*self.responders, *(self.text_responders if text else [])]:
            result = responder(root, words)
            if result is not None:
                if isinstance(result, BaseException):
                    raise result
                return result
        return None


def as_text(result: subprocess.CompletedProcess[Any]) -> subprocess.CompletedProcess[str]:
    """The result with text streams, decoded as kb.git.run would decode them."""
    return subprocess.CompletedProcess(
        result.args, result.returncode, _text(result.stdout), _text(result.stderr)
    )


def as_bytes(result: subprocess.CompletedProcess[Any]) -> subprocess.CompletedProcess[bytes]:
    """The result with byte streams, encoded as UTF-8 when given as text."""
    return subprocess.CompletedProcess(
        result.args, result.returncode, _bytes(result.stdout), _bytes(result.stderr)
    )


def completed(
    returncode: int = 0, stdout: str | bytes = "", stderr: str | bytes = ""
) -> subprocess.CompletedProcess[Any]:
    """A finished Git process with the given streams."""
    return subprocess.CompletedProcess(["git"], returncode, stdout, stderr)


def install(monkeypatch: pytest.MonkeyPatch) -> FakeGit:
    """Patch kb.git.run and kb.git.run_bytes; unmatched calls delegate to the real functions."""
    real_run = git.run
    real_run_bytes = git.run_bytes
    fake = FakeGit(real_run=real_run, real_run_bytes=real_run_bytes)

    def run(root: Path, *words: str, **keywords: Any) -> subprocess.CompletedProcess[str]:
        result = fake.answer(root, words, keywords, text=True)
        if result is None:
            return real_run(root, *words, **keywords)
        return as_text(result)

    def run_bytes(root: Path, *words: str, **keywords: Any) -> subprocess.CompletedProcess[bytes]:
        result = fake.answer(root, words, keywords, text=False)
        if result is None:
            return real_run_bytes(root, *words, **keywords)
        return as_bytes(result)

    monkeypatch.setattr(git, "run", run)
    monkeypatch.setattr(git, "run_bytes", run_bytes)
    return fake


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8").replace("\r\n", "\n")
    return value


def _bytes(value: str | bytes | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, str):
        return value.encode("utf-8")
    return value
