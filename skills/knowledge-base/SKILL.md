---
name: knowledge-base
description: Search and record durable facts a future agent session would need -- domain rules, system behavior, people and ownership, the user's preferences and conventions, and why things were decided. Use before starting any task, to check what is already known. This is the agent's durable memory (~/Knowledge); it is NOT the wiki (~/Wiki, written for the user to read) and NOT Johnny Decimal (~/Documents, which files artifacts like PDFs and receipts).
---

# Knowledge Base

You have access to a knowledge base at `$KNOWLEDGE_BASE`. It contains curated
articles, source documents, and pending observations. All interaction goes
through scripts in `$KNOWLEDGE_BASE/scripts/`.

## Which system is this

Three systems overlap and putting something in the wrong one is how it
gets lost. The split is by **audience**, not by topic:

| System | Audience | Holds |
|---|---|---|
| **Knowledge base** (`~/Knowledge`) | agent sessions | Curated articles loaded for context: domain rules, system behavior, people, preferences, decisions |
| Wiki (`~/Wiki`) | The user, reading | "How my stuff works" — architecture, runbooks, decision logs, written as prose for a person |
| Johnny Decimal (`~/Documents`) | The user, filing | Artifacts: PDFs, scans, receipts, project documents |

This skill is the first one. If what you learned is something a *future
session* needs in order to work — record it here. If it is something the
user would sit down and read — that is the wiki. If it is a file — that
is Johnny Decimal.

Each agent client's own per-project auto-memory is a fourth store. Keep it for
interaction-style feedback ("stop explaining before you act"); anything
durable about systems, domain, or people belongs here, where it is
curated, dated, and searchable across projects.

## Looking things up

Start by searching, not browsing.

1. **Search first.** `$KNOWLEDGE_BASE/scripts/search <term> [term ...]`
   returns matches across knowledge articles, source documents, and pending
   observations. Output format: `<file> | <section> | <matched line>` followed
   by freshness and provenance metadata.
   - Several terms are ANDed at file level. A section containing all terms
     outranks sections that only provide file-level fallback evidence.
   - Results are ranked sections; title and heading evidence outrank body
     evidence. Repeated identical lines count once, and excerpts select up to
     two useful matching lines.
   - Output is capped at 20 sections. Use `--limit N`, `--per-file N`, or
     `--files` to see just which files matched.
   - `--archive` widens the search to archived observations and open
     questions. The default corpora are knowledge articles, source documents,
     and pending observations.
     Open and resolved questions are returned as the `question` corpus with
     their state; they are knowledge gaps or question records, not evidence.
   - Use `--path PATH` for a content-relative file or directory,
     `--topic NAME` for a knowledge topic directory, and
     `--corpus TYPE` for one or more of `knowledge`, `sources`,
     `pending`, `archive`, or `questions`. The default
     corpora are `knowledge`, `sources`, and `pending`;
     `--archive` adds the archive and question corpora.
   - Use `--text-only` for metadata-free section text or `--json` for
     structured output. The two modes cannot be combined.
     H2 search results include the numeric locator needed by
     `section --number`; `top` and frontmatter-title results include
     direct `--top` and `--title` commands.

2. **Narrow with toc.** If search gives too many results or you need to
   explore a topic area, use `$KNOWLEDGE_BASE/scripts/toc` to scan section names.
   - `toc --depth 1` — just topic names (one line per file)
   - `toc --depth 2` — H2 section names (the primary content units)
   - `toc --depth 3` — H3 subsections with dot numbers (1.1, 1.2)
   - `toc --path knowledge/some-dir/` — scope to a subdirectory
   - `toc --dirs` — show the file/directory tree

3. **Load a section.** `$KNOWLEDGE_BASE/scripts/section --file <path> --number N` loads one
   H2. Use `--number N.M` for an H3 subsection. Use `--heading "text"` for
   a case-insensitive substring match on any heading level. Use `--top` for
   prose before the first H2 and `--title` for a frontmatter title. Normal
   output includes the content-relative path, locator, corpus, freshness, and
   provenance. Use `--text-only` for only the section body or `--json` for one
   structured object. Use `--references` to retrieve the complete provenance
   list from frontmatter; combine it with `--json` for structured output.

Retrieval displays at most five provenance references. Structured results also
include `reference_count` and `references_truncated`; use `section --references`
when the complete list is required.

**Always load the minimum content needed.** Do NOT read entire knowledge
files. The toc → section hierarchy is the compression scheme — scan the
index, then load only what's relevant.

## Recording observations

When you learn something non-obvious during a task — the user corrects you,
states a preference, shares domain knowledge, or you discover something
unexpected — capture it immediately:

```bash
$KNOWLEDGE_BASE/scripts/observe --title "<one-line summary>" --body "<details>"
```

### Rules

- **Only observe if `KNOWLEDGE_OBSERVE=1`** is set in your environment.
  Check before calling. Subagents do not get this variable.
- **Capture immediately.** Do not wait until the task is done.
- **One observation per concept.** Three things learned = three calls.
- **Be specific.** "Use uv + PEP 723 for standalone scripts" is good.
  "Use modern tooling" is bad.
- **Include concrete details:** exact commands, error messages, version
  numbers, who told you.
- **Attribute when possible.** If the user says "Dana told me X," include
  Dana's name and role in the observation body. The curator preserves
  inline attribution in knowledge articles.

### What to observe

- Corrections ("no, we don't do X, we do Y because...")
- Domain rules and business logic
- People and roles ("Jake owns the deploy pipeline")
- Preferences and conventions ("always use snake_case in this repo")
- System behavior and gotchas
- Historical context ("we switched from X to Y after the outage in March")

Don't observe ephemeral state ("the build is broken right now") or things
already captured in the knowledge base.

## Recording questions

When you notice a gap — a system, person, or process referenced but not
covered in the knowledge base — flag it:

```bash
$KNOWLEDGE_BASE/scripts/ask --title "Who owns the feature-flag service?" --context knowledge/deploys/canary.md
```

- `--context` is optional. Links the question to a knowledge area.
- `--body` adds detail about why the gap matters.

Questions are reviewed during curation passes.

## Freshness

Knowledge articles carry a `verified` date and a `ttl` in frontmatter.
`ttl` is the article's own answer to how fast it rots:

| `ttl` | Stale after | Typical content |
|---|---|---|
| `people`, `status` | 14 days | People, roles, org, active projects |
| `process` | 60 days | Processes and workflows |
| `domain` | 180 days | Domain rules, system behavior |
| *absent* | 60 days | Unclassified |

`$KNOWLEDGE_BASE/scripts/stale` lists what is past its threshold.

If an article is past its `ttl`, retrieval labels it `stale`; treat its claims
with skepticism and verify against live sources before acting on them. Missing
or malformed dates are labeled `unknown` or `invalid`, never `fresh`. Source
documents under `sources/` use `synced` instead — the date the local copy was
pulled. `search`, `section`, and `stale` share the same thresholds and date
comparison.

## Script reference

All scripts are at `$KNOWLEDGE_BASE/scripts/<name>`.

| Script | Purpose |
|---|---|
| `search <term> [term ...] [--json\|--text-only] [--path PATH] [--topic NAME] [--corpus TYPE]` | Search ranked sections with metadata |
| `evaluate-retrieval --fixture FILE [--baseline FILE]` | Measure retrieval against a versioned question fixture |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT \| --top \| --title) [--json\|--text-only]` | Extract a section or search fallback with metadata |
| `section --file FILE --references [--json]` | Return the complete provenance reference list |
| `observe --title "..." --body "..."` | Record an observation |
| `pending [--full] [--count]` | List uncurated observations |
| `batch start|status|defer` | Persist and resume a curation batch |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `archive FILENAME [--all]` | Move observations to archived |
| `stale [--days N] [--path DIR]` | List articles needing re-verification |
| `lint [--path DIR] [--strict]` | Check articles against the structural conventions |
| `commit -m "..."` | Commit curation work under the write lock |
| `sync [--status]` | Pull and push the content repo |
| `init [--path DIR]` | Initialize an empty content repo |
| `status` | Summary stats |
| `context` | Compact summary for session injection |

`sync` verifies a successful fetch and an available `origin/<branch>` tracking
ref before reporting counts. Normal and `--status` runs return nonzero when
remote state cannot be verified; they do not report cached counts as current.
