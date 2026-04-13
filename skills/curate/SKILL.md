---
name: curate
description: Process pending observations into the knowledge base. Run this to curate new observations into knowledge articles.
user-invocable: true
allowed-tools:
  - "Bash(${CLAUDE_SKILL_DIR}/../scripts/*)"
---

# Curator

You are the knowledge base curator. This knowledge base is an external memory
and context layer for Claude sessions helping the user do their job.

The goal is comprehensive coverage of everything the user knows that a future
Claude session might need: business logic, institutional history, technical
stack, best practices, preferences, people, org structure, processes, and
domain knowledge.

## What belongs in the knowledge base

Almost everything. The bar for inclusion is: **"Could any future Claude
session plausibly need this to do better work?"**

Examples of what belongs:

- Business rules and domain logic ("returns are processed on T+2")
- How systems work, why they were built that way, known gotchas
- Technical choices and the reasoning behind them
- The user's preferences for how work should be done
- People: who owns what, who to ask about what, reporting structure
- Processes: how deploys work, how decisions get made, review workflows
- Historical context: why something is the way it is, past incidents
- Environment and tooling: what's installed, how it's configured

Examples of what does NOT belong:

- Ephemeral state ("the build is currently broken")
- Raw debugging transcripts with no extractable lesson
- Exact duplicates of what's already captured

When in doubt, include it. Thin coverage is the main risk, not bloat. The
curator can always reorganize later.

## Workflow

1. Run `${CLAUDE_SKILL_DIR}/../scripts/pending --full` to read all pending observations.
2. Run `${CLAUDE_SKILL_DIR}/../scripts/toc --depth 2` to see the current knowledge structure.
3. For each observation, decide what to do (see Decision Framework below).
4. Execute your decisions --- edit knowledge files directly under
   `content/knowledge/`.
5. Move each processed observation to `content/observations/archived/`.
6. Review open questions (see Open Questions below).
7. Commit all changes as a single batch.

If there are no pending observations, check open questions anyway (step 6),
then stop if there's nothing to do.

## Decision Framework

For each observation:

### Add to existing article

The observation fits an existing topic. Add it as:

- A new H2 section if it's a distinct subtopic.
- Additional content under an existing H2 if it extends what's there.
- Use `${CLAUDE_SKILL_DIR}/../scripts/section` to read the relevant section before editing, so you
  don't lose existing content.

### Create new article

The observation covers a topic with no existing home. Create a new file in
`content/knowledge/`. Think about where a future agent would look for this
information and name the file accordingly.

### Merge observations

Multiple pending observations relate to the same topic. Synthesize them into a
single coherent addition rather than adding each verbatim.

### Discard (rare)

The observation is purely ephemeral or an exact duplicate. Still archive it
--- never delete observations.

## Knowledge Domains

Organize articles by domain. These are not rigid categories --- use judgment.
A file can cover whatever scope makes sense. But think in terms of:

- **Systems** --- how things work technically (services, data flows, infra)
- **Business** --- domain logic, rules, processes, compliance
- **People** --- org structure, ownership, expertise, contacts
- **Practices** --- how the user and their team prefer to work
- **History** --- why things are the way they are, past decisions, incidents
- **Tools** --- dev environment, CLI tools, configurations, workflows

A single file like `deploy-pipeline.md` might span systems + practices +
history. That's fine. Organize by what you'd search for, not by taxonomy.

## Article Conventions

### Context window budget

LLM context windows fill up fast. The entire point of this knowledge base is
that agents load a lightweight index (`toc`), then pull only the specific
sections they need (`section`). This only works if you write articles that are
actually decomposable into small, self-contained pieces.

The hierarchy IS the compression scheme:

1. `toc --depth 1` --- topic names only (~1 line per file). Agent scans this
   to decide which files are relevant.
2. `toc --depth 2` --- H2 section names (~5-15 lines per file). Agent picks
   the specific section it needs.
3. `section --number N` --- the actual content. This is what hits the context
   window.

Step 3 is the expensive one. **Keep each H2 section short enough to be worth
loading.** If an H2 would exceed ~30-50 lines, split it into multiple H2s or
push detail into H3 subsections (which can be loaded individually via `section
--number 1.2`).

A 500-line H2 defeats the entire system. Ten 50-line H2s with clear names is
infinitely better. If you think you need a 500 line H2, perhaps it needs to be
promoted to an H1.

### Structure

- **H1** --- Topic name. One per file. Broad enough to group related
  subtopics, specific enough that the name alone tells an agent whether to
  look inside.
- **H2** --- The primary content unit. Each must stand alone. An agent will
  load one H2 via `section` without seeing the rest of the file. Name it so
  the `toc` listing is enough to judge relevance.
- **H3+** --- Supporting detail within a subtopic. Use when an H2 has distinct
  sub-parts but they're too small to be their own H2. Agents can load
  individual H3s via `section --number`.

### Voice

- Terse, factual, reference-style.
- Include commands, code, config, or examples where they make the knowledge
  actionable.
- Strip session-specific framing ("I learned that..."). Keep the durable fact.
- Preserve *why* and *context* --- not just what, but the reasoning. "We use X
  because Y" is more valuable than "We use X."

Example --- observation says:

> "Discovered while debugging staging that macOS aggressively caches DNS.
> Flush with dscacheutil -flushcache && sudo killall -HUP mDNSResponder."

Curated:

> ## DNS Cache (macOS)
>
> macOS caches DNS aggressively. To flush:
>
> ```
> dscacheutil -flushcache
> sudo killall -HUP mDNSResponder
> ```

Example --- observation says:

> "Talked to Dana, she said the reason deploys to prod only happen before 2pm
> is that the SRE team needs time to monitor before end of day, and they got
> burned by a 4pm deploy that paged oncall at 2am."

Curated:

> ## Deploy Window
>
> Production deploys must complete before 2:00 PM local time. The SRE team
> requires a monitoring buffer before end of day. This policy was adopted
> after a late-afternoon deploy caused a 2 AM oncall page.
>
> Source: Dana (SRE lead).

### Frontmatter

```yaml
---
title: "Topic Name"
updated: 2026-03-23
verified: 2026-03-23
sources:
  - observations/archived/20260323T174030-18ee.md
---
```

- `updated` --- date of last curator edit.
- `verified` --- date the article's content was last confirmed accurate by a
  human or by the curator cross-checking against live sources. Set to today
  when you verify an article's claims still hold, even if you don't change the
  content. A session reading an article can compare `verified` against the
  current date and the type of content (people/roles rot fast, domain rules
  rot slowly) to judge how much to trust it.
- `sources` --- observation files that contributed. Append on update.

### Granularity

- Each H2: aim for 10-50 lines. Shorter is better.
- Each file: split when it exceeds ~10 H2 sections.
- Prefer many small files over few large ones. A file with 3 H2 sections is
  fine. An agent that needs one fact shouldn't have to scan past 20 section
  titles in `toc` output to find it.

### When to use directories

Directories add a level to the hierarchy. Use them when a domain has enough
subtopics to warrant grouping:

```
content/knowledge/deploys.md                  # fine when deploy knowledge is small
content/knowledge/deploys/                    # better when it grows
content/knowledge/deploys/rollbacks.md
content/knowledge/deploys/canary.md
content/knowledge/deploys/feature-flags.md
```

The directory name is free metadata --- an agent running `toc --dirs` sees the
tree and can scope with `toc --path knowledge/deploys` before loading any file.
Promote a file to a directory when it outgrows a single file.

The curator can reorganize freely --- move sections between files, split,
merge, promote files to directories. Update `sources` frontmatter accordingly.

## Source Documents

`content/sources/` holds local markdown copies of external reference documents
(training manuals, desktop instructions, policy docs). These are **not**
knowledge articles --- they're stored as-is from the source system, not
rewritten into the KB's voice or structure.

### What belongs in `sources/` vs `knowledge/`

- **`sources/`** --- Full text of an external document that sessions need to
  read in detail. Stored as clean markdown with minimal editing. Examples
  inclue meeting notes, white papers, etc.
- **`knowledge/`** --- Curated, structured articles written by the curator.
  May synthesize information from multiple sources.

A knowledge article might extract key facts from a source document. The source
document is the full reference for when a session needs more depth.

### Source document frontmatter

```yaml
---
title: "Incident Response Runbook"
canonical: "https://docs.google.com/document/d/1-n1dt9-.../edit"
synced: 2026-03-31
---
```

- `canonical` --- URL of the authoritative version in the source system.
- `synced` --- date the local copy was last pulled from canonical.

### Re-syncing

During curation passes, check `synced` dates on source documents. If a source
document's `synced` date is older than ~1 month, re-pull from the canonical
URL and update the `synced` date. Use the `gdrive` skill (or appropriate tool)
to fetch the current version.

Knowledge articles that reference source documents should list the local
path in their `sources:` frontmatter (e.g., `sources/incident-response-runbook.md`).

### Committing

Include `sources/` in commits:

```bash
git add knowledge/ observations/ questions/ sources/
git secure-commit -m "Curate: <brief summary>"
```

## Archiving Observations

After processing, move each observation:

```bash
cd content/
git mv observations/pending/FILENAME observations/archived/FILENAME
```

Do this for every observation, including discarded ones. The archive is
the complete record of everything we've ever seen.

## Committing

After all edits and moves, commit everything in one batch. The content
directory is its own git repo:

```bash
cd content/
git add knowledge/ observations/
git secure-commit -m "Curate: <brief summary of what changed>"
```

## Open Questions

Questions live in `content/questions/open/` as individual markdown files.
They represent gaps in the knowledge base --- things the curator or other
sessions noticed but couldn't answer.

### File format

```markdown
---
title: "Short question"
source: curator
context: knowledge/deploys/canary.md   # optional --- omit if no article exists yet
created: 2026-03-24
---

Optional body with context about why this matters or where the gap was noticed.
```

`context:` is optional. Some questions are about topics that don't have
articles yet, or are cross-cutting.

### During curation

After processing observations (step 6), run `${CLAUDE_SKILL_DIR}/../scripts/questions` to see all
open questions. For each topic area you touched during this curation run, also
check `${CLAUDE_SKILL_DIR}/../scripts/questions --path <area>`.

For each open question:

- **Answerable now:** The observations you just processed, or knowledge you
  just wrote, contain the answer. Update the relevant knowledge article (or
  create one), then move the question to `content/questions/resolved/`.
- **Has a home now:** The question references a topic that now has an article.
  Update the `context:` field to point to it. Leave it open.
- **Still unanswered:** Leave it. Don't force an answer.

### Creating new questions

When you spot a gap during curation --- an observation references a system,
person, or process that has no knowledge article and you can't fill it from
what you have --- create a question in `content/questions/open/`. Use the
observation timestamp convention for filenames: `YYYYMMDDTHHMMSS-XXXX.md`.

Examples of good questions:

- "What are the exact canary promotion thresholds? Percentages needed."
- "Who owns the feature-flag service now that the platform team reorged?"
- "How does the deploy freeze calendar work during holiday weeks?"

### Committing

Include `questions/` in the commit:

```bash
cd content/
git add knowledge/ observations/ questions/
git secure-commit -m "Curate: <brief summary>"
```
