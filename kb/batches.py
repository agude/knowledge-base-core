"""Curation batch manifests: observations/batches/<id>.tsv.

A manifest is a header line and one tab-separated row per member:
filename, original_sha256, status (pending, complete, deferred),
disposition, destination. Both implementations read and write it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kb import platform

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


def member(manifest: Path, name: str) -> Member | None:
    """The first row for name, or None."""
    for line in platform.read_text(manifest).split("\n")[1:]:
        fields = line.split("\t")
        if fields[0] == name:
            fields += [""] * (5 - len(fields))
            return Member(*fields[:5])
    return None


def complete(manifest: Path, name: str, disposition: str, destination: str) -> None:
    """Mark name complete with its disposition, rewriting the manifest in place."""
    text = platform.read_text(manifest)
    out = []
    for index, line in enumerate(text.split("\n")):
        fields = line.split("\t")
        if index and fields[0] == name and line:
            fields += [""] * (5 - len(fields))
            fields[2:5] = ["complete", disposition, destination]
            line = "\t".join(fields)
        out.append(line)
    platform.write_text(manifest, "\n".join(out))
