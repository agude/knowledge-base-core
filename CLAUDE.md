# Knowledge Base

An external memory and context layer for Claude sessions on this machine.
The goal is comprehensive coverage of everything the user knows that might
help a future Claude session do better work: business logic, institutional
history, technical stack, best practices, preferences, people, org structure,
processes, and domain knowledge.

Located at `$KNOWLEDGE_BASE` (this directory).

## Structure

- `scripts/` — All interaction goes through these scripts.
- `content/` — Separate content repo (.gitignored). Contains:
  - `knowledge/` — Curated articles. H1 = topic, H2 = sections.
  - `sources/` — Local copies of external reference documents (training manuals, desktop instructions, policy docs). Stored as clean markdown with frontmatter tracking the canonical URL and last-sync date.
  - `observations/pending/` — Raw observations awaiting curation.
  - `observations/archived/` — Processed observations kept for provenance.
  - `questions/open/` — Knowledge gaps flagged by the curator or other sessions.
  - `questions/resolved/` — Answered questions kept for provenance.

## Scripts

All paths are `$KNOWLEDGE_BASE/scripts/<name>`.

| Script | Purpose |
|---|---|
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and numbered H2 sections |
| `section --file FILE (--number N \| --heading TEXT) [--exact]` | Extract a section (`--number` = H2 only; `--heading` = any level) |
| `search "<query>"` | Search knowledge, sources, and pending observations |
| `observe --title "..." --body "..."` | Record an observation (auto-commits) |
| `pending [--full] [--count]` | List uncurated observations |
| `questions [--path DIR] [--file F] [--full] [--all]` | List or read open questions |
| `ask --title "..." [--context FILE] [--body "..."]` | Record an open question |
| `resolve --file F [--answer "..."]` | Resolve a question (move to resolved/) |
| `status` | Summary stats (article/observation counts, last update times) |
| `context` | Print dynamic summary (topic list, pending count) |

Run `context` to see current state before working with the knowledge base.

## Reading knowledge

Always start by searching, not browsing.

1. `search "<query>"` — returns `<file> | <section> | <matched line>`
2. `toc` — scan topic/section names to find relevant files
3. `section --file <path> --number N` — load only the section you need

**Always use `section` to pull the minimum content needed.
Do NOT Read entire entry files.**

## Recording observations

When the user corrects you, states a preference, or you discover something
non-obvious during a task, capture it immediately:

```
scripts/observe --title "<one-line summary>" --body "<observation text>"
```

- Capture IMMEDIATELY. Do not wait until the task is done.
- Be specific. "Use uv + PEP 723" is good. "Use modern tooling" is bad.
- Include concrete details: exact commands, error messages, version numbers.
- One observation per concept. If you learned three things, make three calls.
- It's OK to capture things that seem minor. The curation agent filters later.

## Freshness

Each knowledge article has a `verified` date in its frontmatter — the last
time the content was confirmed accurate. When reading an article, compare
`verified` against today's date and the type of content:

- **People, roles, org structure** — stale after ~2 weeks.
- **Active initiatives, deadlines, project status** — stale after ~2 weeks.
- **Processes and workflows** — stale after ~2 months.
- **Domain rules, regulations, system behavior** — stale after ~6 months.

If an article's `verified` date exceeds these thresholds for its content
type, treat claims with appropriate skepticism and verify against live
sources before acting on them.

## Rules

- **Use scripts, not direct file I/O**, for observations and reading.
- **Only observe if `KNOWLEDGE_OBSERVE=1`** is set in your environment.
  Subagents do not get this variable. Only top-level sessions observe.
- **Do NOT edit entries directly.** Curated entries under `content/knowledge/`
  are maintained exclusively by the curation agent. To record new knowledge,
  always use `observe`.
- **The curator is the exception.** It reads and writes knowledge files
  directly. It runs from this directory with its own skill.

## Entry structure and context-window budget

The `toc` → `section` hierarchy is the compression scheme. An agent scans
the TOC to find relevant files, picks a section heading, then loads only
that section. This only works if entries are decomposable into small,
self-contained pieces.

**Heading conventions:**
- **H1** — Topic name. One per file.
- **H2** — The primary content unit. Each must stand alone.
- **H3+** — Supporting detail within an H2.

**Granularity targets:**
- Each H2: 10–50 lines. Shorter is better.
- Each file: split when it exceeds ~10 H2 sections.
- Prefer many small files over few large ones.

## Questions (knowledge gaps)

When you notice a gap — a system, person, or process referenced but not
covered in the knowledge base — record it with `ask`. The curator reviews
open questions during each curation pass.
