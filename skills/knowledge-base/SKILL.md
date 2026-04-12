---
name: knowledge-base
description: Look up, record, and manage knowledge base content. Use when the user asks to find information, record something, or work with the knowledge base.
user-invocable: true
---

# Knowledge Base

You have access to a knowledge base at `$KNOWLEDGE_BASE`. It contains curated
articles, source documents, and pending observations. All interaction goes
through scripts in `$KNOWLEDGE_BASE/scripts/`.

## Looking things up

Start by searching, not browsing.

1. **Search first.** `scripts/search "<query>"` returns matches across
   knowledge articles, source documents, and pending observations. Output
   format: `<file> | <section> | <matched line>`.

2. **Narrow with toc.** If search gives too many results or you need to
   explore a topic area, use `scripts/toc` to scan section names.
   - `toc --depth 1` — just topic names (one line per file)
   - `toc --depth 2` — H2 section names (the primary content units)
   - `toc --depth 3` — H3 subsections with dot numbers (1.1, 1.2)
   - `toc --path knowledge/some-dir/` — scope to a subdirectory
   - `toc --dirs` — show the file/directory tree

3. **Load a section.** `scripts/section --file <path> --number N` loads one
   H2. Use `--number N.M` for an H3 subsection. Use `--heading "text"` for
   a case-insensitive substring match on any heading level.

**Always load the minimum content needed.** Do NOT read entire knowledge
files. The toc → section hierarchy is the compression scheme — scan the
index, then load only what's relevant.

## Recording observations

When you learn something non-obvious during a task — the user corrects you,
states a preference, shares domain knowledge, or you discover something
unexpected — capture it immediately:

```bash
scripts/observe --title "<one-line summary>" --body "<details>"
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
scripts/ask --title "Who owns the feature-flag service?" --context knowledge/deploys/canary.md
```

- `--context` is optional. Links the question to a knowledge area.
- `--body` adds detail about why the gap matters.

Questions are reviewed during curation passes.

## Freshness

Knowledge articles have a `verified` date in frontmatter. Compare it against
today and the type of content:

| Content type | Stale after |
|---|---|
| People, roles, org structure | ~2 weeks |
| Active initiatives, project status | ~2 weeks |
| Processes and workflows | ~2 months |
| Domain rules, system behavior | ~6 months |

If an article's `verified` date exceeds these thresholds, treat its claims
with skepticism and verify against live sources before acting on them.

## Script reference

| Script | Purpose |
|---|---|
| `search "<query>"` | Search all content |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT)` | Extract a section |
| `observe --title "..." --body "..."` | Record an observation |
| `pending [--full] [--count]` | List uncurated observations |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `status` | Summary stats |
| `context` | Compact summary for session injection |
