"""Curation batch manifests: observations/batches/<id>.tsv.

A manifest is a header line and one tab-separated row per member:
filename, original_sha256, status (pending, complete, deferred),
disposition, destination. Both implementations read and write it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kb import frontmatter, platform

HEADER = "filename\toriginal_sha256\tstatus\tdisposition\tdestination"


@dataclass(frozen=True)
class Member:
    name: str
    sha: str
    status: str
    disposition: str
    destination: str


def directory(content: Path) -> Path:
    return content / "observations" / "batches"


def valid_id(batch_id: str) -> bool:
    return "/" not in batch_id and batch_id.endswith(".tsv")


def fields(line: str, count: int = 5) -> list[str]:
    """Split a row as bash's `IFS=$'\\t' read` does: tab runs are one
    separator, edge tabs are dropped, and the last field keeps the rest."""
    parts = re.split(r"\t+", line.strip("\t"), maxsplit=count - 1) if line.strip("\t") else []
    return parts + [""] * (count - len(parts))


def rows(manifest: Path) -> list[Member]:
    """Every member row, in order; a final unterminated line is not read."""
    members = []
    for line in frontmatter.lines(platform.read_text(manifest)):
        values = fields(line)
        if values[0] != "filename":
            members.append(Member(*values))
    return members


def member(manifest: Path, name: str) -> Member | None:
    """The first row for name, or None."""
    for line in platform.read_text(manifest).split("\n")[1:]:
        if line.split("\t", 1)[0] == name:
            return Member(*fields(line))
    return None


def _update(manifest: Path, name: str, values: dict[int, str]) -> bool:
    """Set fields (by index) on name's rows; False if there is none."""
    out, found = [], False
    for index, line in enumerate(platform.read_text(manifest).split("\n")):
        columns = line.split("\t")
        if index and line and columns[0] == name:
            columns += [""] * (5 - len(columns))
            for position, value in values.items():
                columns[position] = value
            line = "\t".join(columns)
            found = True
        out.append(line)
    platform.write_text(manifest, "\n".join(out))
    return found


def complete(manifest: Path, name: str, disposition: str, destination: str) -> None:
    """Mark name complete with its disposition, rewriting the manifest in place."""
    _update(manifest, name, {2: "complete", 3: disposition, 4: destination})


def defer(manifest: Path, name: str) -> bool:
    return _update(manifest, name, {2: "deferred", 3: "deferred"})
