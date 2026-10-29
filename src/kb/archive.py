"""Pure, byte-preserving rendering for archived curation observations."""

from collections.abc import Sequence
from typing import Literal

from kb import curation, model

Disposition = Literal["incorporated", "duplicate", "ephemeral"]
_ARCHIVE_FIELDS = frozenset({"original_sha256", "curation_batch", "curation_reason"})


def render(
    original: str,
    disposition: Disposition,
    original_sha256: str,
    batch_id: str,
    destinations: Sequence[curation.Destination] = (),
    reason: str | None = None,
) -> str:
    """Append archive provenance while preserving the source's body and line endings."""
    # Constructing the member validates the outcome shape before anything is written.
    curation.Member(
        filename="archive.md",
        original_sha256=original_sha256,
        original_bytes=len(original.encode("utf-8")),
        status="archiving",
        disposition=disposition,
        destinations=tuple(destinations),
        reason=reason,
        archive_sha256="0" * 64,
    )
    curation.validate_run_id(batch_id)

    bom = "\ufeff" if original.startswith("\ufeff") else ""
    text = original.removeprefix(bom)
    document = model.parse("observation.md", text)
    if not document.front_matter_opened or not document.front_matter_closed:
        raise model.FrontMatterEditError("front matter is missing or unclosed")
    existing = sorted({field.name for field in document.front_fields} & _ARCHIVE_FIELDS)
    if existing:
        raise model.FrontMatterEditError("archive fields already exist: " + ", ".join(existing))

    fields: list[tuple[str, str]] = [
        ("original_sha256", original_sha256),
        ("curation_batch", batch_id),
    ]
    if reason is not None:
        fields.append(("curation_reason", reason))

    rendered = text
    previous: str | None = None
    for name, value in fields:
        rendered = model.edit_front_matter(
            rendered,
            name,
            value,
            after=previous,
            quoted=name == "curation_reason",
        )
        previous = name
    return bom + rendered
