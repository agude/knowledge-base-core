"""ATX headings outside fenced code blocks, as every reading command sees them.

A `#` line inside a fence is a shell comment, not a heading. Matches
md_heading in scripts/_lib.sh, except that a heading with an empty name
(`## ##`, `# `) is not a heading at all (audit A-017).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FENCE = re.compile(r"[ \t]{0,3}(`{3,}|~{3,})[ \t]*(.*)")
HEADING = re.compile(r"(#{1,6})\s+(.*)", re.DOTALL)
CLOSING_HASHES = re.compile(r"(.*[^#\s])\s+#+", re.DOTALL)


@dataclass(frozen=True)
class Heading:
    level: int
    text: str


class Headings:
    """Feed lines in order with heading(); fence state carries across lines."""

    def __init__(self) -> None:
        self.fence_char = ""
        self.fence_len = 0

    def track_fence(self, line: str) -> bool:
        """Update fence state; True if the line is a fence delimiter."""
        match = FENCE.fullmatch(line)
        if match is None:
            return False
        marker, info = match.groups()
        char, length = marker[0], len(marker)
        if not self.fence_char:
            # A backtick fence may not carry backticks in its info string.
            if char == "`" and "`" in info:
                return False
            self.fence_char, self.fence_len = char, length
            return True
        # Only a bare marker of the same character, at least as long, closes.
        if char == self.fence_char and length >= self.fence_len and not info.strip(" \t"):
            self.fence_char, self.fence_len = "", 0
        return True

    def heading(self, line: str) -> Heading | None:
        if self.track_fence(line) or self.fence_char:
            return None
        match = HEADING.match(line)
        if match is None:
            return None
        text = match.group(2).rstrip()
        if closed := CLOSING_HASHES.fullmatch(text):
            text = closed.group(1)
        elif re.fullmatch(r"#+", text):
            text = ""
        if not text:
            return None
        return Heading(len(match.group(1)), text)
