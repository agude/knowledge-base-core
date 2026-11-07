"""Parse NUL-delimited porcelain v1 records, including destination-first renames."""

from dataclasses import dataclass

from kb.errors import KbError


@dataclass(frozen=True)
class Entry:
    """One two-letter status and destination, with the source of a rename or copy."""

    code: str
    path: str
    old_path: str | None = None


def parse_porcelain(output: str, *, command: str | None = None) -> list[Entry]:
    """Read `git status --porcelain=v1 -z`, whose second rename field is the source."""
    prefix = f"{command}: " if command else ""
    if output and not output.endswith("\0"):
        raise KbError(f"{prefix}Git returned malformed NUL-delimited status")
    fields = output.split("\0")[:-1]
    entries: list[Entry] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if len(record) < 4 or record[2] != " ":
            raise KbError(f"{prefix}Git returned malformed NUL-delimited status")
        code, path = record[:2], record[3:]
        old_path = None
        if "R" in code or "C" in code:
            if index >= len(fields) or not fields[index]:
                raise KbError(f"{prefix}Git returned malformed rename status")
            old_path = fields[index]
            index += 1
        entries.append(Entry(code, path, old_path))
    return entries
