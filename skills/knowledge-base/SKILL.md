---
name: knowledge-base
description: Search and record durable facts a future agent session would need -- domain rules, system behavior, people and ownership, the user's preferences and conventions, and why things were decided. Use before starting any task, to check what is already known. This is the agent's durable memory (~/Knowledge); it is NOT the wiki (~/Wiki, written for the user to read) and NOT Johnny Decimal (~/Documents, which files artifacts like PDFs and receipts).
---

# Knowledge Base

The tooling checkout is at `$KNOWLEDGE_BASE`; it contains the scripts used to
access the content repo. `KB_CONTENT_DIR` selects the content repo and defaults
to `$KNOWLEDGE_BASE/content`. It contains curated articles, source documents,
and pending observations. All interaction goes through scripts in
`$KNOWLEDGE_BASE/scripts/`.

Keep these roots separate. Do not set `KNOWLEDGE_BASE` to the content repo.

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

Use `kb`, the lookup tool. It reads its content repository from
`~/.config/kb/config.toml`, so no path is needed. Each command answers in one
call.

1. **Recall.** `kb recall QUERY...` finds the curated sections (knowledge
   articles and source documents) that answer a query. The first three print in
   full, and the next few are listed.
   - Each printed section starts with a header line:
     `locator | heading | freshness | sources`. Freshness is
     `fresh, verified DATE`, `stale, verified DATE (ttl T)`, `unknown`,
     `invalid`, or `source, synced DATE`. `, conflict` marks an unresolved
     conflict. Check stale content against a live source before acting on it.
   - Locators are `PATH#N` for an H2 section (with its H3s), `PATH#N.M` for an
     H3 section, `PATH#top` for the prose before the first H2, and `PATH#title`
     for the title. Pass any printed locator to `kb read` unchanged.
   - Dates, paths, flags, and negation words stay in the query. Write a flag
     with its dashes; its bare word also matches.
   - `--limit N` sets how many sections print in full. `--in PATH` limits the
     search to a file or directory.
   - Pending observations that match are listed under "Uncurated (pending, not
     yet verified)". When no section matches, the matching observations and
     questions are listed as "Evidence". A transcript line shows its matching
     text, not its title.
   - A query that matches nothing prints one line. Rephrase once with the key
     nouns. If that also finds nothing, the knowledge is absent.

2. **Explore.** `kb map [PATH] [--depth 1|2|3]` lists the articles under PATH
   (default `knowledge`). Depth 1 counts articles per directory. Depth 2 lists
   each article with its H2 sections. Depth 3 adds the H3 sections.

3. **Read.** `kb read LOCATOR... [--sources]` prints what each locator names,
   under a header line. `kb read PATH` prints the file's outline and its prose
   before the first H2. `--sources` prints each locator's sources, one per line.
   A missing section prints the locators that exist.

**Always load the minimum content needed.** Recall the sections, then read only
the locators you need.

Section metadata is an optional `<!-- kb-section: ... -->` comment on the first
nonblank line after an H2 or H3. It sets that section's `verified`, `ttl`, and
`sources`. Recording and curation still use the scripts in the sections below.

## Recording observations

When you learn something non-obvious during a task — the user corrects you,
states a preference, shares domain knowledge, or you discover something
unexpected — capture it immediately:

```bash
$KNOWLEDGE_BASE/scripts/observe --title "<one-line summary>" --body "<details>"
```

### Rules

- **Observation capture is enabled when `KNOWLEDGE_OBSERVE` is unset or `1`,**
  after the host's session-start lifecycle has initialized a buffer; set it to
  `0` to disable automatic capture. Claude and Codex shell adapters remain
  no-ops if session-start was skipped. Check the value before relying on a
  host adapter. Codex keeps a private per-session initialization marker so a
  swept buffer can be recreated; normal flush clears the marker. Subagents do
  not get this variable. An enabled session that cannot create its buffer
  reports failure through the adapter's existing retries; Codex still emits
  its required `{}` response. Uninitialized sessions remain no-ops.
- **Capture immediately.** Do not wait until the task is done.
- **One observation per concept.** Three things learned = three calls.
- **Be specific.** "Use uv + PEP 723 for standalone scripts" is good.
  "Use modern tooling" is bad.
- **Include concrete details:** exact commands, error messages, version
  numbers, who told you.
- **Preserve useful attribution in raw observations.** If the user says
  "Dana told me X," include Dana's name and role in the observation body.
  Curated articles keep source references; inline attribution belongs only
  where authority, ownership, uncertainty, or conflicting reports matter.
  Routine framing such as "Alex confirmed" does not belong in article prose.

When a source reference is missing, search both pending and archived paths in
content Git history. Restore the original evidence when available. Otherwise
review the affected claims before replacing or removing the reference, and
record any unresolved evidence gap. Passing lint confirms reference validity;
it does not establish that a source supports a claim. Keep strict validation
enabled and run full content lint after the repair.

Host adapters retry a failed `session-append` once. If both attempts fail, the
shell adapter reports failure; Codex still returns its required `{}` response.
The persistence contract is at least once, so a post-write failure can
duplicate a raw transcript line. Repeated prompt or stop hook deliveries are
also retained as separate records because these payloads provide no stable
event identity for deduplication. Curation must treat the transcript as
evidence rather than an idempotent event log. The shell adapter's shutdown
hook flushes synchronously and returns failure while preserving the buffer when
the flush fails; this favors recoverability over a shorter host shutdown
deadline.

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

Numeric TTLs use decimal days, including leading zeroes. Numeric values above
106751991167300 days are invalid because their seconds would overflow.

If an article is past its `ttl`, retrieval labels it `stale`; treat its claims
with skepticism and verify against live sources before acting on them. Missing
or malformed dates are labeled `unknown` or `invalid`, never `fresh`. Source
documents under `sources/` use `synced` instead — the date the local copy was
pulled. `search`, `section`, and `stale` share the same thresholds and date
comparison.

## Script reference

All scripts are at `$KNOWLEDGE_BASE/scripts/<name>`.

For lookups, use `kb recall`, `kb map`, and `kb read` as described above.
`search`, `toc`, and `section` remain for curation and for options `kb` does
not have yet.

| Script | Purpose |
|---|---|
| `search <term> [term ...] [--query TEXT] [--relax] [--explain] [--json\|--text-only] [--path PATH] [--topic NAME] [--corpus TYPE]` | Search ranked sections with metadata |
| `evaluate-retrieval --fixture FILE [--baseline FILE]` | Measure retrieval against a versioned question fixture |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT \| --top \| --title) [--json\|--text-only]` | Extract a section or search fallback with metadata |
| `section --file FILE --references [--json]` | Return the complete provenance reference list |
| `observe --title "..." --body "..."` | Record an observation |
| `pending [--full] [--count] [--preview]` | List observations or preview the curation queue |
| `batch start [--files FILENAME ...]|status|defer` | Persist and resume a curator-selected batch |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `archive FILENAME [FILENAME ...]` | Archive explicit observations |
| `archive --batch ID --disposition TYPE [--destination PATH] FILENAME` | Complete one persisted batch member |
| `stale [--days N] [--path DIR] [--sections]` | List articles or sections needing re-verification |
| `lint [--path DIR] [--strict] [--batch ID]` | Check articles against the structural conventions |
| `commit -m "..."` | Commit curation work under the write lock |
| `sync [--status] [--no-push]` | Pull and push the content repo |
| `init [--path DIR]` | Initialize an empty content repo |
| `status` | Summary stats |
| `context` | Compact summary for session injection |
| `doctor [--require CAPABILITY]` | Diagnose runtime and installation requirements |

The repository's public question-mode evaluation lives under
`tests/fixtures/retrieval-question-v1/`. The ten-case fixture is labeled
`post_implementation`; `retrieval-question-pre-change-v1.json` runs the same
question strings as literal searches on the same corpus and is the frozen
`pre_change` control. The separate comparison fixture pairs literal, strict
question, and relaxed cases. These artifacts have distinct baselines and must
not overwrite one another. The cases cover normalization, paraphrase,
punctuation, alias-routing, temporal, conflict, and abstention.
`temporal-judgments.json` is a separate manual-answer artifact: use it to
distinguish retrieving a historical section from selecting the correct
current claim. Retrieval metrics alone do not establish answer correctness.

Capture requirements are capability-specific. Retrieval uses Bash 4 or newer
and the shared shell utilities; JSON encoding requires od and AWK. JSON parsing
for session flushing, host
adapters, and evaluation requires `jq`; `session-append` can encode stdin
without jq. Curation uses Git and a SHA-256 utility, while development checks
use ShellCheck, Bats, and just. The optional Pi checks use Node and npm.

The shell utilities have explicit portability boundaries: `stat -c` and
`stat -f`, `date -d` and `date -j`, and `sha256sum` and `shasum -a 256` are
paired fallbacks. Recursive ordering requires NUL-safe `sort -z`, section
locators require `sort -V`, and bounded scans require `find -maxdepth`; these
features have no safe text-line substitutes. Entrypoint bootstrapping uses
`readlink -f`; shared path validation has a manual symlink fallback for BSD
`readlink`, but hosts still need a compatible entrypoint resolver. Associative
arrays and `mapfile` require Bash 4 or newer. Node, npm, SQLite, and network
services are optional and outside the shell gate.

Run `scripts/doctor` for read-only diagnostics. Add `--require retrieval`,
`--require capture`, `--require curation`, `--require sync`,
`--require development`, or `--require adapters` when a missing capability
must return nonzero. The check uses only temporary capture files and never
creates a real observation.

For prompts or responses that may be large or multiline, send the message
through stdin:

```bash
printf '%s' "$message" |
  scripts/session-append --file "$buffer" --role user --message -
```

Pass `--message` once. Repeating it, including a mixture of stdin and argument
forms, fails before capture; empty input remains a no-op and non-empty input
keeps its Unicode and trailing newlines.

`session-flush` parses the JSONL stream into a private temporary transcript and
passes it to `observe` through stdin. Parse, write, or commit failures leave
the original buffer for recovery, as do interrupted flushes. A rejected
observation commit leaves both the generated pending observation and the
source buffer so a retry cannot discard the evidence. Host adapters preserve
their at-least-once retry behavior; a post-write failure can still produce a
duplicate raw line.

### Curation queue preview

Run `$KNOWLEDGE_BASE/scripts/pending --preview` explicitly when starting a
manual curation pass. It produces a bounded report for the batch-selectable,
top-level pending files, containing the oldest valid age, observation and
`session-transcript` counts, byte volume, metadata warnings, and deterministic
lexical topic hints. Normal `pending` listing, counting, and `--full` access
remain recursive. The hints are suggestions, not assignments, and preview
generation makes no LLM calls. Empty queues and invalid metadata are reported
without printing observation bodies, so large transcripts do not expand the
preview.

Topic preview matches explicit `topic:` metadata directly. Otherwise it samples
the title and at most 8 KiB of file content, excluding frontmatter, numeric-only
tokens, and generic words. A topic with multiple meaningful words needs two
distinct matches; a one-word topic needs one. Hints remain suggestions, not
batch selections.

The curator agent selects a bounded filename list, then starts it with
`batch start --files FILENAME ...`. `batch start` without `--files` retains
the compatibility behavior of selecting every top-level pending file. After
processing a persisted batch, run
`$KNOWLEDGE_BASE/scripts/batch status BATCH_ID`. Its report reads the manifest's
dispositions and destinations, lists bounded deferred work, and retains the
existing pending/complete/deferred counts. Newly arrived observations are not
part of that report unless a new batch selects them.

Batch input budgets count source-file bytes, including frontmatter. Automatic
selection orders valid `created` timestamps, breaks equal timestamps by
filename, and places missing or invalid timestamps after valid files in
filename order. Exact fits are selected. A zero-byte preview selects nothing;
`batch start` reports that no item fits. Explicit over-budget selections fail
before a manifest is created, and excluded or newly arrived observations
remain pending rather than becoming completable members of the batch.

Archive only completed members with explicit filenames. `archive --all` is a
manual bulk-maintenance operation, not a curation command: it can archive
observations that arrived after the batch was selected.

When a stale article was retrieved during the current curation pass, prioritize
it when its path matches a queue topic hint or an incorporated destination.
Keep that path in the working notes because access telemetry is not stored.
Use `stale` and inspect the affected claims before changing `verified`.
Reading or retrieving an article does not refresh its verification date.

`sync` verifies a successful fetch and an available `origin/<branch>` tracking
ref before reporting counts. Normal and `--status` runs return nonzero when
remote state cannot be verified; they do not report cached counts as current.
