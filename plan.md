# Knowledge Base System Review — Improvement Plan

First review: 2026-07-02. Re-reviewed and expanded: 2026-08-08.
Scope: structure, mechanics, and correctness of the tooling — not article
content.

## What changed since 2026-07-02

Measured on 2026-08-08:

| Metric | 2026-07-02 | 2026-08-08 |
|---|---|---|
| Knowledge articles | 81 | 128 |
| Pending observations | 49 | 1 |
| Archived observations | — | 1,366 (918 session transcripts) |
| SessionStart injection | ~10.8 KB | **12.3 KB / 486 lines** |
| `toc --depth 1` | 258 lines | **404 lines** |
| Tests | passing | passing (89) |

- **F4 (backlog) is resolved.** The weekly manual curation cadence is
  working; pending sits at 1, not 49.
- **F7 (README drift) is resolved.** The README now documents
  `observations/pending|archived`, the two-root pattern, the frontmatter
  schema, and heading numbering correctly.
- **F1 (injection size) got worse**, not better — it grew 14% because it
  scales with article count and nothing was done to break that coupling.
- **F3 (search), F5 (transcript fidelity), F6 (freshness drive), F8
  (lateral links), F9 (memory-system overlap) are unchanged.** No `sync`
  script, no `ttl:` frontmatter, no turn threshold at flush.
- `stale` now reports **37 stale, 0 missing date** — up from 20+.

The 2026-07 plan was about cost and process. This pass audited the scripts
themselves and found **correctness bugs that silently lose content**. Those
outrank everything in the original plan.

## Architecture (as observed)

- Two repos: `knowledge-base-core` (`scripts/`, `skills/`, `tests/`) and
  `content/` (its own git repo, remote `git@github.com:agude/knowledge.git`:
  `knowledge/`, `observations/{pending,archived}`,
  `questions/{open,resolved}`, `sources/`).
- Loading: `session-start` (coat-tree `SessionStart`) injects `CLAUDE.md` +
  `toc --depth 1` + optional `content/CLAUDE.md`, sets `KNOWLEDGE_OBSERVE=1`
  and `KNOWLEDGE_SESSION_FILE`, creates a session buffer, sweeps orphans.
- Capture: `session-prompt` (UserPromptSubmit) and `session-stop` (Stop)
  append to a JSONL buffer in `/tmp/knowledge-sessions/`; `session-end`
  (SessionEnd) flushes the whole transcript as one raw observation.
- Retrieval: `search` (grep -F -i) → `toc` (heading index) → `section`
  (load one H2/H3). The hierarchy is the compression scheme.
- Curation: manual `/curate` distills pending observations into articles,
  maintains `verified`, handles questions.
- Guardrails: `pretool-allow` auto-approves the scripts; `locked_commit`
  serializes writes; `break_stale_git_lock` clears crashed `index.lock`.

## What is working

- The toc → section two-stage retrieval is the right shape, and the
  curation discipline (cut-not-split, repo-owns-its-conventions) is
  visibly holding: 128 articles at 836 KB is a tight corpus.
- The capture → curate → archive provenance chain is better than most
  published systems, and the weekly manual pass is now keeping up.
- `verified` dates address a failure mode mature systems handle poorly.
- Locking, orphan recovery, 89 tests, CI: solid plumbing.

---

## Critical findings — silent content loss

### F10. Code fences corrupt `toc` and truncate `section`

`toc` and `section` both match `^#{1,6}[[:space:]]+` with no fenced-block
tracking. A shell comment inside a ```` ```bash ```` block is parsed as a
heading.

Two distinct failures, both silent:

1. **`section` truncates.** A `# comment` inside a fence is read as an H1;
   `section` stops at "the next heading at the same or higher level," so
   the section ends there. Verified:

   ~~~
   $ scripts/section --file knowledge/shell/find-recipes.md \
       --heading "Dangling symlinks"
   ## Dangling symlinks

   ```bash
   ~~~

   Three lines returned. The rest of the section — every `find` recipe it
   exists to hold — is dropped, with exit status 0 and no warning.

2. **`toc` invents topics.** Those same lines print as file titles at
   `--depth 1`, so the session injection currently advertises topics named
   `Primary targets`, `Install`, `Remove snap version`,
   `All dangling symlinks in $HOME`, and `source  destination`.

Scope: **9 of 128 articles, 18 phantom headings.** Concentrated exactly
where the KB is most useful — `shell/`, `linux/`, `docker/`,
`infrastructure/` — because those articles are mostly commands. Any article
whose code blocks contain `#` comments is affected, and the failure grows
with every command-heavy article the curator writes.

This is the single highest-severity defect in the system: the retrieval
layer returns confidently wrong, truncated answers.

### F11. `search` silently discards every argument after the first

`QUERY="${1:-}"`. `search synology nas` searches only `synology` and
returns 59 lines as if the second term were honored. There is no error and
no indication that the query was narrowed. Verified.

Related, same line: any query beginning with `-` is consumed as a flag.
`search "-h"` prints the help text; `search "--all"` prints the help text.
Both exit 0.

Combined with F3 (no AND, no ranking, no limit — `search "the"` returns
2,971 lines), the entry point the skill tells every session to use "first"
fails in three different silent ways.

### F12. `context` reports an empty knowledge base

`context` gates its topic listing on
`compgen -G "$KNOWLEDGE_DIR/*.md"` — a top-level-only glob. Every article
now lives in a subdirectory, so the check fails and the script prints:

```
Topics: (none yet)
```

with 128 articles present. Verified. `context` is documented in the README,
in `CLAUDE.md`, and in the `knowledge-base` skill's script table as the
"compact summary for session injection." Any session that runs it is told
the knowledge base is empty.

---

## Security findings

### F13. `pretool-allow` auto-approves arbitrary chained commands

The hook takes the first whitespace-delimited token, resolves its
directory, and — if it matches its own `scripts/` — returns
`permissionDecision: allow` **for the entire command string**. Verified:

```
$ printf '{"tool_input":{"command":"/home/agude/Knowledge/scripts/status; \
    echo PWNED > /tmp/pwn.txt"}}' | scripts/pretool-allow
{"hookSpecificOutput":{...,"permissionDecision":"allow",...}}
```

Everything after `;`, `&&`, `|`, a newline, or inside `$(…)` rides along
unprompted. These are **global** coat-tree hooks, so this applies in every
project, and the identical implementation is installed twice —
`010.knowledge` and `020.wiki` (`~/Wiki/scripts/pretool-allow`).

The realistic trigger is not the user typing that; it is prompt injection.
An agent reading a malicious observation, source document, or web page can
be induced to run one command whose first token is a KB script.

Fix: allow only when the command is a single simple command — reject if it
contains any of `; & | \` $( ) < > newline` outside the quoted argument
positions — and drop `allow` to a no-op (fall through to normal
permissioning) otherwise. Fix both copies.

### F14. `SESSION_DIR` is a predictable shared path with no ownership check

`/tmp/knowledge-sessions` is created with `mkdir -p` and default umask, and
every user prompt in every session is written there. On a multi-user host,
another user who wins the race to create that directory receives the full
transcript stream. `set -euo pipefail` also means a `mkdir`/`touch` failure
against a foreign-owned directory aborts `session-start` before it emits
any context.

Fix: use `${XDG_RUNTIME_DIR:-/tmp}/knowledge-sessions-$(id -u)`, create it
`mkdir -p -m 700`, and verify ownership before use.

---

## Robustness findings

### F15. A missing or failing `jq` kills context injection entirely

`session-start` runs under `set -euo pipefail`. Line 50 is
`SESSION_ID="$(echo "$INPUT" | jq -r '.session_id // empty')"`. If `jq` is
absent the assignment fails and the script exits — **before**
`output_context`. Verified: exit 127, **0 bytes of stdout**. No CLAUDE.md,
no topic list, no warning the session can see.

The comment on line 52 ("Fallback if jq fails") is dead code: the `//
empty` fallback is jq syntax and only covers a *missing field*, never a
missing binary. `session-prompt`, `session-stop`, and `session-end` have
the same structure.

Fix: `command -v jq` up front; on failure emit `output_context` and exit 0.
Context injection must never depend on capture succeeding.

### F16. The orphan sweep can silently disable a live session

`session-start` flushes and deletes any `session-*.jsonl` older than 60
minutes. Age is file mtime, and mtime only advances when a turn is
recorded. A session idle for over an hour — the normal state of a terminal
left open — has its buffer flushed and deleted by the *next* session that
starts.

Two consequences. The flushed transcript is a partial session recorded as
complete. And afterwards the live session captures nothing at all, because
`session-prompt` and `session-stop` both begin with
`[[ -f "$SESSION_FILE" ]] || exit 0`. The failure is permanent for that
session and produces no output.

Fix: skip buffers whose `session_id` belongs to a live Claude process, or
recreate the buffer on write instead of exiting when it is missing. The
second is one line and fixes the data loss regardless of the sweep.

This is very likely the answer to the open question *"Do the Stop and
SessionEnd knowledge hooks also break on a transplanted, resumed session?"*
— resolve it against this finding.

### F17. `locked_commit` commits the whole index, and `/curate` ignores the lock

`locked_commit` does `git add "$p"` per path, then `git commit -m "$msg"`
with **no pathspec** — so it commits everything staged in the content repo,
not just its own paths. An `observe` firing while `/curate` has work staged
sweeps that work into a commit titled `Observe: Session transcript (2
messages)`.

The reverse hole is worse: the `curate` skill commits with bare
`git secure-commit` and never acquires `.observe.lock`, so it races
`observe`/`archive`/`ask`/`resolve` from any concurrent session.

Fix: `git commit -m "$msg" -- "$@"`, and route curation commits through
`locked_commit`.

### F18. `--body`-less invocations read stdin unconditionally

`observe` (and `ask`, and `resolve --answer`) fall back to `BODY="$(cat)"`
whenever stdin is not a TTY. Under an agent's Bash tool stdin is not a TTY,
so a malformed call — `--body` omitted, or its value swallowed by quoting —
either blocks on a pipe that never closes or writes an empty-bodied
observation and commits it. Neither is diagnosed.

Fix: require an explicit `--body -` (as `resolve --answer -` already does)
to opt into stdin; error otherwise.

### F19. Second `# H1` headings break the file model

`toc` and `section` assume one H1 per file. Two articles have two:
`knowledge/projects/knowledge-base.md` and `knowledge/projects/wiki.md`.
`toc --depth 1` prints both as separate topics, so the injected map claims
more articles than exist. Nothing enforces the rule.

Fix: a lint pass (below) that fails on a second H1, plus fixing the two
files.

### F20. Small correctness nits

- `pending` prints bare `0` and exits 0 when `observations/pending/` is
  missing, ignoring `--full`/`--count`. It should say
  `No pending observations.` in non-`--count` mode.
- `archive --all` filters `.gitkeep` after a `find -name '*.md'` that can
  never match it — dead code.
- `frontmatter_field` reads the entire file when a file has no
  frontmatter, and mis-parses CRLF files.
- `observe` filenames are `YYYYMMDDTHHMMSS` + 4 hex chars. Two machines
  observing in the same second collide at ~1/65536 — and the collision
  produces a *merge conflict on a content file*, which is exactly the
  scenario the timestamped-filename design exists to avoid. Widen to 8 hex.
- `observe` depends on `xxd`, `session-*` on `jq`, `toc --dirs` on `tree`,
  `_lib.sh` on `pgrep`, `session-start` on `logger`. None are checked; the
  README claims macOS/Linux portability. Add a `doctor` check or graceful
  fallbacks (`od -An -tx1` for `xxd`).

---

## Cost and scale findings

### F21. Injection is now 12.3 KB and 60% of it is formatting

`toc --depth 1` spends **three lines per file** — a blank line, a
`[relative/path.md]` header, and the H1 — for 404 lines total. `--flat`
drops to 148 lines but discards the path, which is the one field a session
needs to call `section --file`. There is no `path — Title` single-line
mode, so the cheap fix is unavailable.

Cost scales linearly with article count and is identical whether the
session is about Docker or bike maintenance. F1's target of ≤2 KB is
unchanged and now further away.

### F22. The archive is write-only memory

`search` covers `knowledge/`, `sources/`, and `observations/pending/`. It
does **not** cover `observations/archived/` (1,366 files, 11 MB, 918 of
them session transcripts) or `questions/`. Anything the curator chose not
to promote is unreachable by every retrieval path in the system — the
archive's stated purpose, provenance, is real, but "we've seen this before"
is not answerable.

11 MB of transcripts against 836 KB of curated knowledge also means clone
and multi-machine sync cost scales with raw capture, not with knowledge.

Fix: `search --all` opting into archived and questions, and reconsider
whether transcripts belong in the same git repo as the articles.

### F23. Trivial transcripts are still captured

306 of 1,366 archived observations (22%) are `Session transcript (2
messages)` — a single prompt and reply. P3's mechanical turn threshold was
never implemented. The backlog is under control, so this is now a git-log
and repo-size cost rather than a curation cost, but it is free to fix.

### F24. Three memory systems, no division of labor

F9 named Claude Code auto-memory. The audit found a third: `~/Wiki` runs
its own `SessionStart` hook (`020.wiki`), its own `pretool-allow`, and
three skills (`wiki`, `wiki-observe`, `write-wiki`) whose descriptions are
near-verbatim duplicates of `knowledge-base`'s ("Use when the user asks to
find information, record something..."). Two systems, indistinguishable
trigger conditions, and both loaded in every session.

`knowledge/projects/wiki.md § Three systems, three audiences` records the
intended split. It is not expressed anywhere an agent reads by default —
not in either skill description, not in either `CLAUDE.md`.

Fix: rewrite both skill `description:` fields so the routing rule is in the
one string the model always sees, and state the boundary in each
`CLAUDE.md`.

### F25. Freshness has no per-type threshold and no `sources/` coverage

Unchanged from F6, plus: the `curate` skill instructs re-syncing
`sources/*.md` when their `synced:` date is older than a month, but `stale`
only reads `verified`, so there is no way to find them. `sources/` is
currently empty, so this is latent.

37 articles are past 60 days, including `user/` content the stated
thresholds say rots in 14.

### F26. `curate` skill is CWD-bound and depends on a personal git alias

The skill hardcodes `cd content/` and `content/knowledge/<file>.md`, which
breaks whenever `KB_CONTENT_DIR` points elsewhere — the exact
configurability the two-root pattern exists to provide. It also calls
`git secure-commit`, a personal alias in the user's `~/.gitconfig`, not
anything this repo ships; a fresh clone fails at the commit step.

The skill also gives three different commit recipes: `git add knowledge/
observations/`, `… questions/`, and `… questions/ sources/`.

Fix: use `$CLAUDE_SKILL_DIR/scripts/…` and a `scripts/commit` wrapper
around `locked_commit`; state the pathspec once.

### F27. CI is thin

`.github/workflows/test.yml` runs `apt-get install -y bats` without
`apt-get update` (breaks whenever the runner image's package index goes
stale) and runs no `shellcheck`. Every bug in F10–F20 is in bash; several
(unquoted arg fallthrough, dead fallback branches, `set -e` interactions)
are exactly what shellcheck flags.

---

## Improvement plan (prioritized)

### P0. Fix the retrieval layer (F10, F11, F12) — do this first

Everything else is optimization; this is correctness.

- **Fence-aware heading parsing.** Add a shared `is_heading` helper in
  `_lib.sh` that tracks ```` ``` ```` and `~~~` fences (including
  info strings and indented fences) and use it in both `toc` and
  `section`. Both must use the *same* helper or their numbering diverges.
- **Regression tests** with a fixture article containing `# comment` lines
  inside a fence: assert `toc` reports exactly the real headings and
  `section` returns the whole section.
- **Lint pass** — `scripts/lint` (also wired into CI) that fails on: a
  second H1, an H2 over ~50 lines, a missing `verified`, a heading inside
  a fence that the parser would once have caught. Run it during `/curate`.
- **`search` argument handling.** Accept multiple terms; use `grep -e` or
  `--` so leading-dash queries are literal; error on an empty query rather
  than printing help for `-h`-shaped input.
- **`context` glob** — replace `compgen -G` with the same recursive `find`
  the rest of the script uses. Add a test asserting a nested-only tree
  lists its topics.

### P1. Close the permission and injection-availability holes (F13, F14, F15)

- Restrict `pretool-allow` to single simple commands; fix both the KB and
  Wiki copies; add a test asserting a chained command is not approved.
- Move the session buffer to a mode-700, uid-scoped directory.
- Guard every `jq` call; never let capture failure suppress injection.

### P2. Shrink and sharpen the injection (F21, F1, F2)

- Add `toc --map`: one line per file, `knowledge/path.md — Title`. Use it
  in `session-start` instead of `toc --depth 1` (404 → 128 lines
  immediately), or a curator-maintained directory-level map (~25 lines)
  with `toc --path <dir>` to drill in.
- Cut the injected `CLAUDE.md` to what the KB is, the map, and "invoke the
  `knowledge-base` skill." The script table and rules live in the skill.
- Append live state from `status`: pending, stale, open-question counts.
- Target: ≤2 KB.

### P3. Make search worth the "search first" instruction (F3, F11, F22)

- Rewrite on ripgrep: multi-term AND within a file, per-file grouping
  ranked by match count, heading-weighted matches, `--limit N` (default
  ~20 lines), and frontmatter lines suppressed unless `--all`.
- `--all` to include `observations/archived/` and `questions/`.
- Optional follow-up: sqlite FTS5 (BM25, porter stemming) rebuilt by a
  content-repo post-commit hook, with grep as fallback. Skip embeddings —
  see "deliberately not doing."

### P4. Capture fidelity and hygiene (F16, F18, F23, F5)

- Recreate the session buffer on write instead of exiting when missing;
  skip live sessions in the orphan sweep. Resolve the open question about
  transplanted/resumed sessions against F16.
- Require `--body -` to read stdin.
- Skip flushing transcripts below a turn threshold (mechanical only — the
  recorded decision to **never pre-distill with a weak model** stands).
- F5 (mid-turn discoveries lost) remains open by design; the mitigation is
  the explicit `observe` habit, not more automated capture.

### P5. Commit integrity (F17, F26)

- `git commit -m "$msg" -- "$@"` in `locked_commit`.
- `scripts/commit` wrapper; route `/curate` through it so curation takes
  the same lock as capture.
- De-CWD the `curate` skill; drop `git secure-commit`; one pathspec.

### P6. Support the weekly manual curation run (F25, F6)

Constraints that still rule out unattended automation: curation on a strong
model is expensive and runs end-of-week against a known budget, and the
content repo spans multiple machines so curation requires a sync first.

- `scripts/sync` — `git pull --rebase && git push` on the content repo.
  Optionally auto-push after `observe`/`session-flush`.
- Pending/stale/question counts in the injection (P2) so the weekly run is
  prompted by visible state.
- `/curate` caps batch size and reports what it deferred.
- During the run: check `stale`, and `ask` for expired people/status
  articles so re-verification enters the existing workflow.

### P7. Per-article freshness metadata (F25)

- Add `ttl:` (or `type:`) to frontmatter — people=14d, process=60d,
  domain=180d. Teach `stale` to read it, defaulting to 60. Teach it
  `synced:` for `sources/`. The curator sets it at write time; the
  thresholds stop being prose in three places.

### P8. Routing and links (F24, F8)

- Rewrite the `knowledge-base` and `wiki` skill descriptions so they are
  distinguishable from the description alone; state the KB/wiki/auto-memory
  boundary in both `CLAUDE.md`s. Proposal unchanged: auto-memory holds
  interaction-style feedback only; durable systems/domain/people knowledge
  goes to the KB; the wiki holds what is written for a human audience.
- "See also" relative links added by the curator when articles relate.
  `section` already carries them to the reader. No tooling change.

### P9. Hygiene (F19, F20, F27)

- Fix the two double-H1 articles.
- `apt-get update` before install in CI; add a `shellcheck` job.
- The F20 nits: `pending` empty-dir output, dead `.gitkeep` filter,
  8-hex observation suffixes, dependency checks (`jq`, `xxd`, `tree`,
  `pgrep`, `logger`).
- Keep per-observation commits — unique timestamped filenames make them
  conflict-free across machines, which multi-machine sync depends on.

### Deliberately not doing

- **Vector database / embeddings.** 128 files. FTS5 + headings + links
  beat the operational cost. Revisit at ~500 articles.
- **Relevance-based per-prompt injection (RAG on UserPromptSubmit).** Adds
  latency to every prompt and duplicates what the model does with one
  `search` call. Make search good instead (P3).
- **Pre-distilling transcripts with a small model at flush time.** What a
  weak extractor drops is invisible to the curator forever, degrading the
  one stage where intelligence matters. Recorded decision; unchanged.
- **Rewriting bash in another language.** The scripts are tested, portable,
  and small. The P0 parser is ~20 lines of awk-or-bash, not a rewrite.
  Reconsider only if P3's FTS work demands it.

## Suggested order

1. **P0** — fence-aware parsing, `search` args, `context` glob, plus
   regression tests and `scripts/lint`. Silent wrong answers first.
2. **P1** — `pretool-allow` restriction, session-dir permissions, `jq`
   guards. Small, and two of the three are security.
3. **P2** — `toc --map` + injection diet. Immediate, measurable token
   savings on every session in every project.
4. **P4/P5** — buffer-recreate one-liner, `--body -`, turn threshold,
   `locked_commit` pathspec, `scripts/commit`.
5. **P3** — search rewrite (the largest single piece of work).
6. **P6/P7** — `sync`, `ttl:`, stale-driven questions as curation habits.
7. **P8/P9** — skill descriptions, "See also", CI, nits.

## Verification commands

Reproduce the P0 findings before and after the fix:

~~~bash
# F10 — truncation (returns 3 lines; should return the whole section)
scripts/section --file knowledge/shell/find-recipes.md \
  --heading "Dangling symlinks"

# F10 — phantom topics in the injection
scripts/toc --depth 1 | grep -E '^(Primary targets|Install|source  dest)'

# F10 — full blast radius
for f in $(find content/knowledge -name '*.md'); do
  awk '/^```/{i=!i; next} i && /^#{1,6}[ \t]/{c++} END{exit !(c>0)}' "$f" \
    && echo "$f"
done

# F11 — second term silently dropped
scripts/search synology nas | wc -l   # == scripts/search synology | wc -l

# F12 — reports an empty knowledge base
scripts/context | head -3

# F13 — chained command auto-approved
printf '{"tool_input":{"command":"%s/scripts/status; id"}}' "$KNOWLEDGE_BASE" \
  | scripts/pretool-allow

# F15 — injection dies without jq
echo '{"session_id":"x"}' | PATH=/usr/bin:/bin scripts/session-start | wc -c
~~~

## Research sources

- [Letta: Agent Memory — how to build agents that learn and remember](https://www.letta.com/blog/agent-memory/) — core-vs-archival memory tiers; consolidation should be asynchronous ("sleep-time"); context engineering framing.
- [The Architecture of Persistent Memory for Claude Code](https://dev.to/suede/the-architecture-of-persistent-memory-for-claude-code-17d) — two-tier CLAUDE.md + store; Haiku extraction at capture time with existing memories as dedup context; confidence × access ranking; recency-only recall pitfall.
- [AI Agent Memory Systems: 2026 Engineering Guide (Letta, LangMem, Mem0, Zep)](https://jobsbyculture.com/blog/ai-agent-memory-systems-guide-2026) — explicit tiers, controlled write policies, retrieval pipelines.
- [A-MEM / CLAG (arXiv)](https://arxiv.org/pdf/2603.15421) — Zettelkasten-style linked notes outperform pure similarity retrieval.
- [Best AI Agent Memory Systems 2026 compared](https://vectorize.io/articles/best-ai-agent-memory-systems) — hierarchical memory + importance scoring + forgetting.
- [Persistent memory via memsearch plugin (Milvus)](https://milvus.io/blog/adding-persistent-memory-to-claude-code-with-the-lightweight-memsearch-plugin.md) — hook-driven capture/retrieval patterns in Claude Code.
