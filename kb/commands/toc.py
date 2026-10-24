"""toc - Generate a table of contents from markdown files.

Scans markdown files and extracts headings. H1 is the file title.
H2s are numbered per file (these are the content units). H3+ are
shown indented under their parent H2 when --depth allows.

Usage:
  toc [--depth N] [--path DIR_OR_FILE] [--flat] [--dirs] [--map]

Options:
  --depth N    Maximum heading level to include (default: 2, i.e., H1 + H2)
  --path PATH  Directory to scan or single file (default: knowledge/)
  --flat       Omit filename grouping, just list headings
  --dirs       Show the directory/file tree
  --map        One line per topic area with an article count

Examples:
  toc                          # H1+H2 from knowledge/
  toc --depth 3                # H1+H2+H3
  toc --path knowledge/topic.md
  toc --depth 1 --flat         # Just topic names, no file headers
  toc --dirs                   # Just show directory/file tree
  toc --map                    # Areas and counts, for session injection

Output format (default):
  [knowledge/networking.md]
  Networking
    1. DNS Resolution
    2. TCP Handshake
       2.1. Client Hello
       2.2. Server Hello
    3. TLS

Output format (--dirs):
  knowledge/
    ach/
      fraud/
        credits.md
        debits.md
    git.md
    networking.md

Output format (--map):
  knowledge/ach/          12
    fraud/                 4
  knowledge/deploys/       7

Counts include nested directories. --map is what session-start injects:
it costs one line per area instead of three per article, and a session
drills in with `toc --path knowledge/<area>`.

Use the section numbers with the `section` script:
  section --file knowledge/networking.md --number 2
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kb import cli, frontmatter, paths, platform
from kb.content import content_dir
from kb.markdown import Headings


def _pad(text: str, width: int) -> str:
    """Left-justify to width bytes, as C printf's %-Ns does."""
    return text + " " * max(0, width - len(text.encode("utf-8", errors="surrogateescape")))


def _directories(top: Path) -> list[Path]:
    found = [Path(directory) for directory, _, _ in os.walk(top)]
    return sorted(found, key=bytes)


def area_map(content: Path, target: Path) -> list[str]:
    """--map: one line per directory holding articles, then the loose files and total."""
    out = []
    files = paths.markdown_files(target) if target.is_dir() else []
    counts: dict[Path, int] = {}
    for path in files:
        for parent in path.parents:
            if parent == target:
                break
            counts[parent] = counts.get(parent, 0) + 1
    for directory in _directories(target) if target.is_dir() else []:
        count = counts.get(directory, 0)
        if directory == target or not count:
            continue
        relative = str(directory).removeprefix(f"{target}/")
        depth = relative.count("/")
        if depth == 0:
            out.append(f"  {_pad(paths.relative(content, directory) + '/', 38)} {count:3d}")
        else:
            out.append(
                f"  {' ' * (depth * 2)}{_pad(directory.name + '/', 38 - depth * 2)} {count:3d}"
            )
    loose = sum(1 for f in files if f.parent == target)
    if loose:
        out.append(f"  {_pad(paths.relative(content, target) + '/ (loose files)', 38)} {loose:3d}")
    out += ["", f"  {len(files)} articles. Drill in with: toc --path <area>"]
    return out


def tree(target: Path) -> list[str]:
    """--dirs: directories and *.md entries, indented by depth (audit A-019)."""
    entries = [target] if target.is_dir() else []
    for directory, dirs, files in os.walk(target):
        base = Path(directory)
        entries += [base / d for d in dirs if not (base / d).is_symlink()]
        entries += [base / f for f in files if f.endswith(".md")]
        entries += [base / d for d in dirs if (base / d).is_symlink() and d.endswith(".md")]
    out = []
    for path in sorted(entries, key=lambda p: os.fsencode(str(p))):
        relative = str(path).removeprefix(str(target))
        if not relative:
            out.append(f"{target.name}/")
            continue
        name = f"{path.name}/" if path.is_dir() else path.name
        out.append(" " * (relative.count("/") * 2) + name)
    return out


def headings(content: Path, path: Path, depth: int, flat: bool) -> list[str] | None:
    """The table of contents for one file, or None if it cannot be read."""
    try:
        text = platform.read_text(path)
    except OSError:
        return None
    out = [] if flat else ["", f"[{paths.relative(content, path)}]"]
    parser = Headings()
    h2 = h3 = 0
    for line in frontmatter.lines(text):
        heading = parser.heading(line)
        if heading is None or heading.level > depth:
            continue
        if heading.level == 1:
            out.append(heading.text)
        elif heading.level == 2:
            h2, h3 = h2 + 1, 0
            out.append(f"  {h2}. {heading.text}")
        elif heading.level == 3:
            h3 += 1
            out.append(f"     {h2}.{h3}. {heading.text}")
        else:
            out.append(" " * ((heading.level - 2) * 2 + 5) + f"- {heading.text}")
    return out


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--depth": "depth", "--path": "path"},
        flags={"--flat": "flat", "--dirs": "dirs", "--map": "map"},
    )
    depth_text = args.get("depth", "2")
    if not (depth_text.isascii() and depth_text.isdigit() and int(depth_text) > 0):
        cli.fail("Error: --depth takes a positive number")  # Audit A-018.
    depth = int(depth_text)
    content = content_dir()
    target = content / "knowledge"
    if "path" in args.values:
        try:
            resolved = paths.resolve(content, args.get("path"))
        except paths.PathError:
            return 1
        if resolved is None:
            cli.fail(f"Not found: {args.get('path')}")
        target = Path(f"{content}/{resolved}")
    if "map" in args.flags:
        if target.exists() and not target.is_dir():
            cli.fail(f"Not a directory: {target}")
        print("\n".join(area_map(content, target)))
        return 0
    if "dirs" in args.flags:
        lines = tree(target) if target.is_dir() else [f"{target.name}/"]
        print("\n".join(lines))
        return 0
    if target.is_dir():
        files = paths.markdown_files(target)
    elif target.is_file():
        files = [target]
    elif target == content / "knowledge":
        files = []  # A missing knowledge directory is an empty one (audit A-035).
    else:
        cli.fail(f"Not found: {target}")
    out: list[str] = []
    for path in files:
        lines = headings(content, path, depth, "flat" in args.flags)
        if lines is None:
            # One warning, and the rest still listed (audit A-036).
            print(f"toc: cannot read {paths.relative(content, path)}", file=sys.stderr)
            continue
        out += lines
    if out:
        print("\n".join(out))
    return 0
