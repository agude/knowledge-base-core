"""stale - List knowledge articles past their freshness threshold.

Reads the `verified` date from each article's frontmatter and compares
it against today. Articles are listed in path order.

Usage:
  stale [--days N] [--path DIR] [--sections] [--count]

Options:
  --days N     Override threshold: flag anything older than N days
  --path DIR   Scope to a subdirectory of knowledge/
  --sections   Report stale and unresolved H2/H3 sections individually
  --count      Print only the number of articles needing attention

Examples:
  stale                        # use default thresholds
  stale --days 30              # flag anything not verified in 30 days
  stale --path knowledge/deploys/

Per-article thresholds come from a `ttl:` field in the frontmatter,
either a number of days or one of these names:

  people    14 days  — people, roles, org structure
  status    14 days  — active initiatives, project status
  process   60 days  — processes and workflows
  domain   180 days  — domain rules and system behavior

Content type cannot be auto-detected, so an article with no `ttl:`
falls back to 60 days. The curator sets it when writing the article;
that is the only place the type is actually known.

Files under sources/ are local copies of external documents, so their
freshness is `synced:` — when the copy was last pulled — rather than
`verified:`.

--days overrides everything, for a one-off review at a chosen depth.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from kb import cli, dates, paths, platform, retrieval
from kb.content import content_dir, nonnegative


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)
    stale: int = 0
    undated: int = 0


def _date(value: str) -> str:
    return value.rsplit("T", 1)[0] if "T" in value else value


def _articles(content: Path, target: Path) -> list[tuple[str, Path]]:
    prefix = f"{content}/"
    return [(str(p).removeprefix(prefix), p) for p in paths.markdown_files(target)]


def _readable(relpath: str, path: Path) -> str | None:
    try:
        return platform.read_text(path)
    except OSError:
        # Skipped with one warning, not reported as undated (audit A-036).
        print(f"stale: cannot read {relpath}", file=sys.stderr)
        return None


def articles(content: Path, target: Path, days: int | None) -> Report:
    report = Report()
    for relpath, path in _articles(content, target):
        text = _readable(relpath, path)
        if text is None:
            continue
        fresh = retrieval.freshness(relpath, text, days)
        if fresh.status == "unknown":
            report.undated += 1
            report.lines.append(f"  [no {fresh.field}]  {relpath}")
        elif fresh.status == "invalid":
            report.undated += 1
            report.lines.append(f"  [bad date] {relpath}  ({fresh.field}: {fresh.value})")
        elif fresh.status == "stale":
            report.stale += 1
            report.lines.append(
                f"  {fresh.age_days:4d} days  {relpath}  ({fresh.field}: {_date(fresh.value)}, ttl {fresh.ttl_days}d)"
            )
    return report


def _override(fresh: retrieval.Freshness, days: int | None) -> None:
    """--days for one section, as bash's section_freshness_with_override."""
    if days is None or fresh.status in ("unknown", "invalid"):
        return
    fresh.ttl_days = days
    epoch = dates.date_epoch(fresh.value.split("T", 1)[0]) or 0
    age = dates.today_epoch() - epoch
    fresh.age_days = retrieval.trunc_days(age)
    fresh.status = "stale" if age > days * 86400 else "fresh"


def sections(content: Path, target: Path, days: int | None) -> Report:
    report = Report()
    for relpath, path in _articles(content, target):
        if _readable(relpath, path) is None:
            continue
        record = retrieval.load(relpath, path)
        for locator in sorted(
            record.sections, key=lambda loc: [int(part) for part in loc.split(".")]
        ):
            selected = record.select(locator)
            fresh = selected.freshness
            _override(fresh, days)
            status = selected.selected.status if selected.selected else "current"
            if fresh.status not in ("stale", "unknown", "invalid") and status == "current":
                continue
            where = f"{relpath}#{locator}"
            if fresh.status == "stale":
                report.lines.append(
                    f"  {fresh.age_days:4d} days  {where}  ({fresh.field}: {_date(fresh.value)}, "
                    f"ttl {fresh.ttl_days}d; status {status})"
                )
            elif fresh.status == "unknown":
                report.lines.append(f"  [no {fresh.field}]  {where}  (status {status})")
            elif fresh.status == "invalid":
                report.lines.append(
                    f"  [bad date]  {where}  ({fresh.field}: {fresh.value}; status {status})"
                )
            else:
                report.lines.append(f"  [status {status}]  {where}")
            report.stale += 1
    return report


def target_for(content: Path, value: str | None) -> Path:
    if value is None:
        return content / "knowledge"
    try:
        resolved = paths.resolve(content, value)
    except paths.PathError:
        raise SystemExit(1) from None
    if resolved is None:
        cli.fail(f"Not found: {value}")
    return Path(f"{content}/{resolved}")


def count(content: Path) -> int:
    """Articles needing attention, as `stale --count` prints."""
    report = articles(content, content / "knowledge", None)
    return report.stale + report.undated


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--days": "days", "--path": "path"},
        flags={"--sections": "sections", "--count": "count"},
    )
    days = (
        nonnegative("--days", args.get("days")) if "days" in args.values else None
    )  # Audit A-023.
    content = content_dir()
    target = target_for(content, args.values.get("path"))
    if not target.is_dir() and not (target == content / "knowledge" and not target.exists()):
        cli.fail(f"Not found: {target}")  # A missing knowledge directory is empty (A-035).
    count_only = "count" in args.flags
    if "sections" in args.flags:
        report = sections(content, target, days)
        if count_only:
            print(report.stale)
        elif not report.stale:
            print("No stale sections.")
        else:
            print("\n".join(report.lines))
            print(f"\n{report.stale} section(s) needing attention.")
        return 0
    report = articles(content, target, days)
    total = report.stale + report.undated
    if count_only:
        print(total)
    elif not total:
        print("No stale articles.")
    else:
        print("\n".join(report.lines))
        print(f"\n{report.stale} stale, {report.undated} missing date.")
    return 0
