# Knowledge Base Reliability and Retrieval Plan

Created: 2026-09-04. Status: tasks 1–8 and 8.5 implemented; task 9 pending.

## Objective

Make curation preserve unfinished work, expose the trustworthiness of retrieved
facts, and measure whether agents recover the evidence they need. Keep Markdown
and Git as the authoritative storage layer.

This plan follows a review of tooling, skills, adapters, tests, CI, and four
sections of one design article. It is not an audit of subject coverage in
`content/`. Four findings below were reproduced with temporary fixtures; the
full test suite was not run during the review.

Use this file as the implementation tracker. Mark acceptance criteria complete
only after verification. Record commands, results, decisions, and remaining
limitations in the implementation log at the end.

## Constraints

- Read applicable `AGENTS.md` instructions and relevant skills before changes.
- Search the knowledge base using its scripts. Exclude `content/` from broad
  repository inspection; sample specific sections only when needed.
- Use temporary content repositories for tests. Do not curate or migrate the
  user's real articles as part of tooling implementation.
- Preserve separate tooling and content roots: `KNOWLEDGE_BASE` identifies the
  tooling installation used by adapters; `KB_CONTENT_DIR` selects content.
- Keep curation manual and budget-driven. Do not introduce scheduled model calls.
- Preserve archived evidence. Deferred observations must remain pending.
- Never refresh `verified` because an article was read or mechanically edited.
- Preserve path confinement, write locking, bounded output, and observation
  opt-out behavior. Do not use `git -C` in new commands or code.
- Keep private evaluation questions and answers out of the public tooling repo.
- Do not add a vector service, graph database, or embedding pipeline without the
  evaluation gate in task 9. Any search index must be locally rebuildable.
- Update CLI help, skills, README examples, callers, and tests together when a
  command contract changes. Document deliberate compatibility changes.

## Order and Dependencies

| Task | Priority | Depends on |
|---|---|---|
| 1. Preserve curation batch boundaries | P0 | None |
| 2. Report synchronization failures accurately | P0 | None |
| 3. Return freshness and provenance with results | P1 | None |
| 4. Establish retrieval evaluation | P1 | None; use task 3 metadata when available |
| 5. Improve section retrieval | P1 | 3, 4 |
| 6. Handle corrections and validate references | P2 | 1, 3 |
| 7. Make the manual curation queue actionable | P2 | 1 |
| 8. Correct documentation and test adapters | P2 | Align docs throughout; finish after 1–7 |
| 8.5. Harden path safety, evaluation, and adapter contracts | P1 | 1–8 |
| 9. Evaluate optional retrieval infrastructure | Conditional | 4, 5 |

Implement tasks 1–8 and 8.5. Task 9 requires a documented decision; adopting
additional infrastructure is conditional on measured failures and improvement.

## 1. Preserve Curation Batch Boundaries

**Finding:** `skills/curate/SKILL.md` permits partial batches but instructs the
curator to run `archive --all --no-commit`. A fixture containing one processed
item and one unreviewed item archived both. New arrivals can suffer the same fate.

**Start with:** `skills/curate/SKILL.md`, `scripts/pending`, `scripts/archive`,
`scripts/commit`, and `tests/archive.bats`.

Capture the batch's explicit filenames before processing. Track dispositions:
incorporated, duplicate, ephemeral, or deferred. Archive only completed items;
the existing archive command already accepts explicit filenames. Persist enough
batch state to resume an interrupted run. Choose a minimal representation rather
than introducing another task-management system.

**Acceptance criteria**

- [x] Processing A while deferring B leaves B pending.
- [x] Observation C arriving after batch selection remains pending.
- [x] Incorporated, duplicate, and ephemeral items are archived with a recorded
  disposition; incorporated items identify their destination article or section.
- [x] An interrupted run can identify completed and unfinished items on resume.
- [x] Repeating completion does not overwrite archived evidence or lose items.
- [x] Missing or changed batch inputs produce actionable diagnostics rather than
  silently reporting full completion.
- [x] Curation instructions use explicit completed filenames instead of `--all`.
- [x] Tests exercise batch membership and interruption behavior with temporary
  repositories, including arrival of an observation after selection.

## 2. Report Synchronization Failures Accurately

**Finding:** `scripts/sync` suppresses fetch failures and initializes remote
counts to zero. A fixture with an unavailable remote returned exit 0 and
`In sync with origin/main.`

**Start with:** `scripts/sync`, `scripts/_lib.sh`, `tests/sync.bats`, and the
curator workflow.

**Acceptance criteria**

- [x] A failed fetch makes both normal sync and `--status` return nonzero and
  state that remote state could not be verified.
- [x] Missing remote branches or unavailable tracking information cannot produce
  a successful "in sync" result.
- [x] Any displayed cached counts are labeled as cached, not current.
- [x] Existing success, ahead, behind, dirty-worktree, `--no-push`, and rebase
  conflict cases retain documented behavior.
- [x] Inspect lock boundaries and recheck mutable preconditions under the lock
  before rebasing or pushing; test relevant concurrent observation behavior.
- [x] The curator synchronizes before selecting a batch. A failed synchronization
  is reported explicitly and is not treated as successful synchronization.
- [x] Tests use local remotes and cover fetch failure without network access.

## 3. Return Freshness and Provenance with Results

**Finding:** `section` returns only heading/body text; search omits verification
metadata. A section verified in 2020 with a 14-day TTL was returned without any
indication that its ownership claim was stale.

**Start with:** `scripts/section`, `scripts/search`, `scripts/stale`,
`scripts/_lib.sh`, and their tests.

Provide compact metadata in normal agent-facing retrieval and structured output
for tooling. Preserve a documented text-only mode for callers that need it.
Choose the exact flags and schema before implementation and document them.

**Acceptance criteria**

- [x] Results identify content-relative path, heading/section locator, and corpus
  type: curated article, source document, pending observation, or archive.
- [x] Curated results include `verified`, applicable TTL, and freshness status.
  Source documents use `synced`; observations are labeled as uncurated evidence.
- [x] Missing or invalid dates are shown as unknown/invalid, never fresh.
- [x] Relevant provenance references are available without loading the whole
  article; article-level references are not misrepresented as claim-level proof.
- [x] Search and section agree with `stale` on thresholds and boundary dates.
  Share freshness logic instead of creating divergent implementations.
- [x] Stale results remain available for historical questions and are labeled.
- [x] Structured output parses correctly for empty results, quotes, Unicode,
  multiline text, and filenames containing spaces; diagnostics stay on stderr.
- [x] Existing output limits remain effective and metadata overhead is measured.
- [x] Reading results never changes content or verification dates.

## 4. Establish Retrieval Evaluation

**Gap:** Command tests exercise behavior but do not establish whether realistic
questions retrieve the evidence needed to answer them.

**Start with:** `tests/search.bats`, `tests/section.bats`, and a new evaluation
runner and fixture format. Keep model-based answer evaluation separate from the
fast, deterministic test suite.

**Acceptance criteria**

- [x] Define a versioned question format containing query, expected supporting
  sections, whether multiple sections are required, and unanswerable status.
- [x] Provide 30–50 representative cases covering exact commands/names,
  paraphrases, cross-article evidence, changed facts, conflicting evidence, and
  absent answers. Public fixtures must be synthetic or sanitized; private cases
  may be loaded from a separately configured location.
- [x] For each answerable case, report whether any required evidence and whether
  all required evidence appear in the top five distinct sections. Report first relevant
  rank, returned bytes, and latency using documented measurement conditions.
- [x] Produce per-case failures as well as aggregate scores. Preserve a baseline
  for the pre-ranking-change implementation.
- [x] Provide an explicit, manually invoked answer-evaluation protocol recording
  correctness, supporting citations, and correct abstention. Do not infer answer
  quality from retrieval metrics alone or incur automatic model charges.
- [x] Document one reproducible command for evaluation, corpus identity, and how
  expected section locators are updated when fixture articles change.

## 5. Improve Section Retrieval

**Finding:** Search adds points for each matching line. Twenty repeated body
mentions outranked an exact title match in a temporary fixture. Terms are ANDed
at file level and displayed excerpts are the first matching lines.

**Start with:** `scripts/search`, shared Markdown parsing, and task 4's baseline.

**Acceptance criteria**

- [x] Rank retrievable sections, retaining file/title context. An exact-title
  match beats an unrelated section containing repeated body mentions in the
  regression fixture.
- [x] Repeated identical lines cannot increase relevance without bound.
- [x] A section containing all query terms ranks above unrelated sections whose
  parent file happens to contain the terms elsewhere. Document any file-level
  fallback used to preserve discovery.
- [x] Excerpts select useful query evidence rather than always taking the first
  matching lines; results give an unambiguous locator for `section`.
- [x] Add documented path/topic and corpus filters. Preserve default coverage of
  knowledge, sources, and pending observations; archive access remains explicit.
- [x] Preserve literal command/identifier searches, fence handling, deterministic
  ties, bounded results, and path confinement.
- [x] Distinguish search execution failures from successful zero-result queries.
- [x] Compare against the frozen baseline: fix the demonstrated repetition and
  excerpt failures, introduce no exact-command regressions, and record any other
  per-case regressions with their resolution or explicit tradeoff.
- [x] Record latency and output-size changes under the same evaluation conditions.

## 6. Handle Corrections and Validate References

**Gap:** Curation explains adding and merging information but lacks an explicit
procedure for contradictory evidence. Structural linting does not validate the
local evidence chain.

**Start with:** `skills/curate/SKILL.md`, `scripts/lint`, and lint fixtures.

**Acceptance criteria**

- [x] Document comparison of source authority, observation date, and effective
  date when a new observation contradicts an existing claim. Newer capture alone
  does not automatically establish authority.
- [x] A worked fixture shows a corrected canonical claim, retained old evidence,
  and a recorded reason/effective date for supersession.
- [x] An unresolved conflict remains explicitly labeled; curation does not
  manufacture agreement or mark conflicting claims verified.
- [x] Partial article updates do not imply unrelated claims were reverified.
- [x] Lint checks local Markdown links and `sources` references for missing files
  and, where supported, missing anchors. Define supported Markdown link forms.
- [x] Relative links, moved articles, fenced examples, and external URLs have
  tests. Structural lint does not fetch external URLs.
- [x] Batch validation accommodates references to observations being archived
  within the same curation transaction and rejects broken final references.
- [x] Real content is not mass-edited to satisfy the new checks; document any
  compatibility findings for a separate curation pass.

## 7. Make the Manual Curation Queue Actionable

**Gap:** Startup counts show workload size but do not identify useful batches or
how much transcript review produces durable knowledge.

**Acceptance criteria**

- [x] Add an explicit preview command or mode showing oldest pending age,
  observation versus transcript counts, input volume, and available topic hints.
- [x] Topic hints are identified as hints; generating the preview needs no LLM.
- [x] Batch completion reports disposition totals, destinations, and deferred
  work using task 1's persisted state.
- [x] Empty queues, malformed metadata, and large transcripts have bounded,
  understandable output and tests.
- [x] Detailed previews are requested explicitly rather than injected into every
  session. Existing compact startup counts remain available.
- [x] Document how to prioritize stale articles that were recently retrieved.
  Access telemetry is optional: if added, keep it local, bounded, separate from
  content Git history, and independent of `verified` dates.
- [x] No unattended curation or scheduled model calls are introduced.

## 8. Correct Documentation and Test Adapters

**Findings:** README setup conflates tooling and content roots. The knowledge-base
skill says default search covers curated articles only, although code includes
sources and pending observations. OpenCode/Pi tests check source strings; CI does
not type-check or execute those TypeScript adapters.

**Start with:** `README.md`, both portable skills, `scripts/install`,
`scripts/adapters/`, `tests/adapters.bats`, `tests/portability.bats`, and
`.github/workflows/test.yml`.

**Acceptance criteria**

- [x] README examples distinguish tooling root from content root and work in a
  temporary installation with content outside the tooling checkout.
- [x] Skills, help, and README agree on search corpora, output metadata, sync
  failures, batch archiving, and correction handling.
- [x] Type-check OpenCode and Pi adapters against documented, reproducibly
  installed SDK versions. Verify current host contracts against primary sources.
- [x] Execute adapter lifecycle tests with mocked host events and temporary
  storage: start, capture, duplicate events, switch/fork where supported,
  disabled observation, failed capture, and shutdown/flush recovery.
- [x] Tests establish behavior rather than merely checking event names in source.
- [x] Preserve existing shell-adapter behavior and core session tests.
- [x] CI runs the adapter checks, Bats suite, ShellCheck, and portability lint.
  Load project-standards and readable-code skills before tooling/code changes.
- [x] Identify stale repo-mechanics claims encountered in sampled KB articles for
  later curation; keep the repository as the authority for implementation details.

## 8.5. Harden Path Safety, Evaluation, and Adapter Contracts

**Findings:** The lint target loop skips path confinement for existing paths, so
an existing file outside `KB_CONTENT_DIR` can be read. The real content tree has
37 pre-existing missing source references across 11 articles and therefore does
not pass strict lint. Retrieval evaluation records unanswerable cases but does
not flag false-positive evidence. Adapter tests use hand-written host types,
append retries can duplicate a post-write failure, and observation-enable
semantics differ between adapters and documentation.

**Start with:** `scripts/lint`, `tests/lint.bats`, `scripts/evaluate-retrieval`,
`tests/adapters.test.ts`, both TypeScript adapters, the observation environment
documentation, and the curation workflow for stale source references.

**Acceptance criteria**

- [x] Every lint target is resolved and confined beneath `KB_CONTENT_DIR`,
  including existing absolute paths and symlinks; outside targets fail without
  reading the file. Add regressions for an existing external file and an escaping
  symlink.
- [x] `KB_CONTENT_DIR=content scripts/lint --path content/knowledge` passes, or
  a documented compatibility/migration policy covers all 37 missing source
  references without weakening reference validation.
- [x] The retrieval evaluator reports false-positive retrieval for unanswerable
  cases and includes a fixture where related distractor evidence is returned.
  That signal participates in regression checks.
- [x] Adapter lifecycle tests use the pinned SDK event and context types, or a
  compile-time contract fixture derived from those declarations, while retaining
  runtime lifecycle coverage.
- [x] Append retry behavior is explicit and tested: either make retries
  idempotent/deduplicated or document and verify at-least-once persistence with
  post-write failure coverage.
- [x] `KNOWLEDGE_OBSERVE` semantics are consistent across TypeScript adapters,
  shell adapters, skills, README, and tests, including the unset environment.
- [x] Update this plan's status, completion checklist, and implementation log to
  distinguish completed tasks 1–8 and 8.5, pending task 9, and the separate task 9
  decision. Record current validation commands and any environment-specific
  test workaround.

## 9. Decide Whether Additional Retrieval Infrastructure Is Needed

Complete this decision after task 5. Do not assume corpus size alone justifies
embeddings or proves that lexical retrieval is sufficient.

**Acceptance criteria**

- [ ] Classify remaining evaluation failures: vocabulary/paraphrase, ranking,
  missing content, stale/conflicting evidence, or answer-generation failure.
- [ ] Record a keep-current-search decision if remaining failures do not justify
  additional infrastructure. This is a valid completion of this task.
- [ ] If ranking/tokenization remains a problem, evaluate section-level SQLite
  FTS5/BM25 as a rebuildable local index before adding a service.
- [ ] If paraphrase misses remain, evaluate optional semantic retrieval alongside
  lexical retrieval; compare fused rankings on the same frozen cases.
- [ ] Adopt an experiment only after recording which failures it fixes, any
  regressions, dependency/model costs, index invalidation behavior, and latency.
- [ ] Any adopted index can be deleted and rebuilt from Markdown, handles edits,
  moves, and deletions, and has a tested unavailable-index fallback.

## Research References

- [LongMemEval](https://arxiv.org/abs/2410.10813): evaluate extraction,
  cross-session reasoning, temporal reasoning, knowledge updates, and abstention.
- [SQLite FTS5](https://www.sqlite.org/fts5.html): BM25 ranking, weighted columns,
  and snippets for an optional local index.
- [LangGraph memory](https://docs.langchain.com/oss/python/concepts/memory):
  scoped memories and separation of immediate and background memory writes.
- [Letta memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks):
  explicitly attached, bounded context; the KB already follows much of this idea.
- [Reciprocal Rank Fusion](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf):
  combine lexical and semantic rankings if hybrid retrieval is justified.

These sources motivate experiments; their benchmark results are not evidence of
improvement on this knowledge base.

## Completion and Handoff

- [x] Tasks 1–8 and 8.5 meet their acceptance criteria; task 9 remains pending
  its separate infrastructure decision.
- [x] Run targeted checks as changes land, then the complete required suite.
  Record actual commands and results; do not reuse historical test counts.
- [x] Review the final diff for unrelated changes and private content leakage.
- [x] Document command compatibility changes and migration requirements.
- [x] Record any remaining limitations with evidence and affected task IDs.
- [x] Update this plan so another session can distinguish completed, deferred,
  and genuinely blocked work without reconstructing the conversation.

## Implementation Log

### 2026-09-04 — Task 1

Implemented persisted curation batches in `observations/batches/*.tsv`.
`scripts/batch start` captures selected pending filenames and SHA-256 hashes;
`batch status` reports completed, pending, and deferred work and detects missing
or changed inputs; `batch defer` records deferral without moving the observation.
`scripts/archive --batch ...` requires explicit batch members, validates hashes,
records disposition and incorporated destinations in archived frontmatter, and
does not overwrite an existing archive. Updated the curation skill and README
to prohibit `archive --all` for curation.

Verification:

- `bash -n scripts/batch scripts/archive` — passed.
- `bats tests` — 282 tests passed.
- `git diff --check` — passed.

Remaining limitation: batch manifests are working-tree state until the normal
curation commit; the manifest and archive changes are committed together by
`scripts/commit` after processing.

### 2026-09-05 — Task 2

Updated `scripts/sync` to hold the content lock through remote verification,
history inspection, rebase, and push. Fetch failures, missing remote-tracking
refs, and history-count failures now return nonzero with an explicit message
that remote state could not be verified. The script rechecks the worktree after
fetch and before rebase or push, excluding only its lock directory from dirty
state detection. Rebase conflicts remain in place for resolution.

Updated the curator workflow to synchronize before selecting a batch and stop
when synchronization fails. Documented the synchronization contract in the
README and portable knowledge-base skill.

Verification:

- `bats tests/sync.bats` — 15 tests passed.
- `bats tests/*.bats` — 291 tests passed.
- `bash scripts/portability-lint` — passed.
- `shellcheck -x -P scripts -s bash scripts/sync` — passed.
- `git diff --check` — passed.

Remaining limitation: the repository-wide ShellCheck command still reports
pre-existing warnings in `scripts/batch`; no warnings were introduced by
`scripts/sync`.

### 2026-09-05 — Task 3

Added shared retrieval metadata helpers in `scripts/_lib.sh`. `search` and
`section` now classify corpus type, expose freshness from `verified` or
`synced`, label missing and invalid dates, and expose provenance references with
article/document scope. Archived observations include disposition and
destination metadata. `stale` now uses the same TTL and date comparison logic.

Added `--json` structured output and documented `--text-only` compatibility
output. Search JSON is a bounded object with result totals and truncation state;
section JSON is one object containing its locator and multiline content. Normal
output retains the previous path/section/text shape and appends compact
metadata. Updated the README and portable knowledge-base skill.

Verification:

- `bats tests/search.bats tests/section.bats tests/stale.bats` — 69 tests passed.
- `bats tests` — 304 tests passed.
- `bash scripts/portability-lint` — passed.
- `shellcheck -x -P scripts -s bash scripts/_lib.sh scripts/search scripts/section scripts/stale` — passed.
- `git diff --check` — passed.
- Metadata measurement on one fixture: section output grew from 43 to 286 bytes (+243); one search result grew from 51 to 167 bytes (+116). Existing `--limit` and `--per-file` line caps remain effective.

Feedback follow-up:

- Open and resolved questions now use the distinct `question` corpus with an
  explicit `provenance.state`; `--archive` remains the opt-in selector.
- Default provenance output is capped at five references. JSON reports the full
  `reference_count` and `references_truncated`; `section --references [--json]`
  retrieves the complete frontmatter list.
- A 100-reference fixture produced 35 bytes of text-only search output and 617
  bytes of bounded JSON output (582 bytes of metadata overhead, five displayed
  references); explicit complete-reference JSON was 3,406 bytes for all 100.
- `FRESHNESS_TODAY_EPOCH=1768089600` boundary tests verify that a date exactly
  at the TTL remains fresh while the preceding date is stale across `stale`,
  `search`, and `section`.

Compatibility change: default `search` and `section` output now includes
metadata. Callers requiring the prior raw output must pass `--text-only`.

### 2026-09-05 — Task 4

Added `scripts/evaluate-retrieval`, a deterministic evaluator that runs
`search --json` against versioned JSON fixtures. Version 1 cases define a
query, expected content-relative section locators, whether all expected
sections are required, and unanswerable status. Answerable locators are
validated against the selected corpus before search runs. Reports include
per-case failures, distinct-section top-five any/all evidence coverage, first
relevant rank, full-ranking and bounded response bytes/latency, aggregate
scores, fixture/corpus IDs, and SHA-256 identities.

Added a public synthetic corpus and 36-case fixture covering exact
commands/names, paraphrases, cross-article evidence, changed facts,
conflicting evidence, and absent answers. Added a frozen baseline containing
pre-ranking-change locators and outcomes. Baseline comparison reports fixture
or corpus mismatches, changed cases, regressions, and improvements. It detects
pass-to-fail changes, later first-relevant ranks, lost any/all evidence, and
lower matched-evidence counts; it is manually invoked and can fail explicitly
on regressions.

Documented a separate manual answer-evaluation protocol. It records answer
correctness, supporting section citations, abstention, and abstention
correctness outside the public tooling repository. Updated the README and
portable knowledge-base skill with the evaluator contract and reproducible
commands.

Verification:

- `bats tests/evaluate_retrieval.bats` — 7 tests passed.
- `bats tests/*.bats` — 311 tests passed.
- `shellcheck -x -P scripts -s bash scripts/evaluate-retrieval` — passed.
- `bash scripts/portability-lint` — passed.
- `git diff --check` — passed.
- Public baseline comparison with `--fail-on-regression` — 36 unchanged cases,
  zero regressions.


Baseline measurement on 2026-09-05: 31 answerable cases, 18 passed, 13
failed, and 5 unanswerable. Any-required-evidence and all-required-evidence
coverage were both 18/31 (58.06%). The report separates full-ranking latency
from bounded top-five latency and records both response sizes. Timing uses
high-resolution `date +%s%N` on this host; the evaluator documents a
second-resolution fallback for platforms without that format.

Remaining limitation: the evaluator measures retrieval coverage only. The
manual protocol is documented but has no automatic answer-quality scorer or
private answer set, by design.

### 2026-09-05 — Task 5

Reworked `scripts/search` to rank Markdown sections instead of individual
matching lines. Section scores retain title and file context, reward complete
term coverage, penalize file-level fallback sections, cap repeated evidence,
and use up to two highest-value distinct lines as excerpts. Results retain
content-relative paths, titles, section locators, metadata, and bounded output.
Search execution failures now return nonzero instead of being masked by the
pipeline.

Added `--path`, `--topic`, and repeatable `--corpus` filters. Default coverage
remains knowledge articles, source documents, and pending observations;
`--archive` remains the explicit addition of archived observations and
questions. Updated the README and portable knowledge-base skill with the
section ranking, fallback, excerpt, limit, and filter contracts.

Added regression tests for exact-title ranking over repeated body mentions,
duplicate-line saturation, complete-section ranking over file-level fallback,
useful excerpts, path/topic filters, and corpus filters. Updated evaluator
tests for section-level raw result counts and the frozen-baseline comparison.

Verification:

- `bats tests` — 319 tests passed.
- `scripts/evaluate-retrieval --fixture tests/fixtures/retrieval-v1/retrieval-v1.json --content-dir tests/fixtures/retrieval-v1/content --baseline tests/fixtures/retrieval-v1/retrieval-v1.baseline.json --fail-on-regression --json` — 36 cases, zero regressions, zero exact-command failures.
- Frozen baseline comparison: 18 cases changed because section-level output consolidates repeated line results; no ranking, evidence, or status regressions.
- Evaluation response bytes under the same corpus and commands: frozen baseline full/top totals 19,046/18,575; current section retrieval 16,056/16,056. Current measured full/top search latency was 2,315/2,281 ms.
- `shellcheck -x -P scripts -s bash scripts/search` — passed.
- `bash scripts/portability-lint` — passed.
- `git diff --check` — passed.

### 2026-09-05 — Task 5 review follow-up

Made complete term coverage a primary ranking tier for actual sections, so a
section containing every query term outranks a partial section whose score is
inflated by title and heading evidence. Exact frontmatter-title results remain
the strongest synthetic title result to preserve the title-ranking contract.
Fixed file-only aggregation so multiple candidates from one file still
produce one file result.

Added numeric H2 locators to search JSON and normal output. Duplicate H2
headings can now be retrieved with `section --number N`. Added `section
--top` and `section --title` for direct retrieval of search's top and
frontmatter-title results, including JSON command locators. Updated the
retrieval evaluator to distinguish numeric and command locators.

Added regression coverage for title-plus-heading fallback ranking, duplicate
H2 locators, and top/title retrieval. Updated the README and portable
knowledge-base skill with the locator and ranking contracts.

Verification:

- `bats tests` — 323 tests passed.
- `shellcheck -x -P scripts -s bash scripts/search scripts/section scripts/evaluate-retrieval` — passed.
- `bash scripts/portability-lint` — passed.
- `git diff --check` — passed.
- Frozen retrieval comparison — 36 cases, zero regressions, zero exact-command failures.

Current frozen-evaluation totals under the same fixture are 16,407 full/top
response bytes and 2,270/2,309 ms full/top latency. The remaining baseline
changes are the existing 18 section-level consolidation changes.

### 2026-09-05 — Task 6

Documented correction handling in `skills/curate/SKILL.md`. Contradictory
evidence is compared by source authority, observation date, and effective date;
capture recency alone does not select the canonical claim. The workflow now
requires a supersession reason and effective date, retains old evidence, labels
unresolved conflicts explicitly, and leaves article-level `verified` unchanged
when an edit did not recheck unrelated claims.

Extended `scripts/lint` to validate supported relative Markdown links and
content-root-relative `.md` entries in `sources:`. It checks heading fragments
against ASCII heading slugs, ignores external URLs and fenced or inline-code
examples, rejects absolute or escaping paths, and reports missing targets and
anchors. `lint --batch BATCH_ID` temporarily accepts an unchanged selected
observation at its future `observations/archived/` path; a final lint after
archiving remains strict.

Added a correction fixture containing a canonical replacement, superseded
evidence, effective date, reason, and explicit unresolved conflict. Added tests
for relative, moved, anchored, fenced, inline-code, external, missing, and
batch-aware references.

Added explicit `conflict: unresolved` frontmatter to the correction fixture and
exposed it as `conflict.status` in `search` and `section` metadata, independently
of freshness. Updated the pre-commit hook to lint the full knowledge tree when a
staged Markdown link target under `knowledge/` or `sources/` is renamed or
deleted, catching unchanged inbound links without linting observation archive
moves; updated the curator workflow with the same full-tree check and added
clean-fixture regressions for both operations plus an installed-hook archive
regression with an unrelated legacy broken reference.

Scoped archive handling so pending-to-archived additions remain compatible with
the installed hook, while removals or moves out of `observations/archived/`
trigger full-tree validation. Added an installed-hook regression proving an
unchanged `sources:` reference blocks archived evidence deletion.

Verification:

- `bats tests` — 335 tests passed.
- `bash -n scripts/lint` — passed.
- `shellcheck -x -P scripts -s bash scripts/lint` — passed.
- `bash scripts/portability-lint` — passed.
- `git diff --check` — passed.
- `KB_CONTENT_DIR=content scripts/lint --path content/knowledge` — expected
  compatibility failure: 37 pre-existing missing source references across 11
  articles; no body-link failures after inline-code exclusion. Real content was
  not edited.

### 2026-09-05 — Task 7

Added the explicit `scripts/pending --preview` queue report. It shows pending
age from valid `created` metadata, observation versus `session-transcript`
counts, exact and human-readable byte volume, bounded metadata warnings, and
lexical topic hints derived from article headings or optional `topic:` metadata.
The report labels hints as suggestions, samples at most 8 KiB per item for
lexical matching, and never prints observation bodies. Existing `--count`,
default listing, and compact session-start counts remain unchanged.

Extended `scripts/batch status` to report incorporated, duplicate, and
ephemeral totals; grouped incorporated destinations; and bounded deferred work
from the persisted TSV manifest. Added tests for mixed queue previews, empty
and malformed inputs, large transcripts, and completed/deferred batch reports.
Documented manual stale-article prioritization in the README and both portable
workflow skills. No access telemetry, unattended curation, or scheduled model
calls were introduced.

Verification:

- `bats tests/pending.bats tests/batch.bats` — 18 tests passed.
- `bats tests` — 339 tests passed.
- `bash -n scripts/pending scripts/batch` — passed.
- `shellcheck -x -P scripts -s bash scripts/pending scripts/batch` — passed.
- `bash scripts/portability-lint` — passed.
- `git diff --check` — passed.

Remaining limitation: topic hints are lexical suggestions, not curation
assignments, and recent retrieval access is not persisted. Stale-article
prioritization therefore uses the current run's working notes and queue or
batch paths.

### 2026-09-05 — Task 7 review corrections

Corrected the review findings in the queue preview and batch report. Unknown
persisted dispositions now increment the batch's invalid-item count and make
`batch status` return nonzero. `pending` and `batch start` now use the same
top-level pending-file discovery rule. Preview metadata reads are capped at
64 KiB per file, topic samples at 8 KiB, and article metadata at 256 files;
file sizes use filesystem metadata when available instead of scanning full
transcripts. Topic matching uses an inverted word index and retains only the
best eight ranked hints for output. Regular `pending` listing, counting, and
full display remain recursive; only `pending --preview` and `batch start` use
the top-level batch-selection rule.

Added regression coverage for corrupt manifests and nested observations, plus
a 320-article and 256 KiB transcript preview fixture. The topic corpus cap is
reported in the preview when reached. Added coverage for escaped YAML topic
labels and recursive non-preview access to nested observations. The preview
enumerates only batch-selectable top-level files and labels that scope in its
report. Updated the README and portable workflow skills to document the
distinction.

Verification:

- `bats tests/pending.bats tests/batch.bats` — 22 tests passed.
- `bats tests` — 343 tests passed.
- `bash -n scripts/pending scripts/batch` — passed.
- `shellcheck -x -P scripts -s bash scripts/pending scripts/batch` — passed.
- `bash scripts/portability-lint` — passed.
- `git diff --check` — passed.

### 2026-09-05 — Task 8

Separated the tooling root from the content root throughout the README,
knowledge-base skill, installer help, and executable examples. The tooling
checkout is selected by `KNOWLEDGE_BASE`; `KB_CONTENT_DIR` selects content and
defaults to the checkout's `content/` directory. Documented search corpora,
retrieval metadata, sync failure semantics, explicit batch archiving, and
correction handling consistently. Updated `sync` and `archive` help text to
match the documented command forms.

Added exact SDK pins and a Node/TypeScript check runner. OpenCode is checked
against `@opencode-ai/plugin` 1.18.29 and Pi against
`@earendil-works/pi-coding-agent` 0.85.0. The adapters now retain failed
append/flush work for retry and use the current Pi shutdown/start lifecycle
for session replacement. The lifecycle tests use mocked host events, a
temporary content Git repository, temporary session storage, and injected
core-command failures. They verify capture, duplicate suppression, context
injection, disabled mode, append retry, flush retry, and Pi new/fork session
replacement.

Replaced source-string checks for TypeScript host events with executable
adapter tests. Added the `just check` CI gate for ShellCheck, portability lint,
TypeScript type-checking, the Bats suite, and adapter tests. Existing shell
tests remain in the gate.

Sampled repo-mechanics claims for later curation; the repository remains the
implementation authority. `knowledge/projects/knowledge-base.md` §3 says the
content repository must be cloned at `~/Knowledge/content`, which conflicts
with the supported external `KB_CONTENT_DIR` layout. `knowledge/projects/claude-hooks.md`
§2 says the installer creates lifecycle symlinks when
`~/Knowledge` exists, but the current installer only migrates legacy links,
installs shared skills, and installs the content-repo hook. Both claims need a
future content curation pass; no curated article was edited in this task.

Verification:

- `just check` — ShellCheck and portability lint passed; `npm ci` installed 169
  packages with 0 vulnerabilities; TypeScript type-check passed; 342 Bats
  tests passed; 6 adapter lifecycle tests passed.
- `bash /home/agude/.agents/skills/project-standards/scripts/audit.sh
  /home/agude/Knowledge` — all required runner, CI, README, license, and
  canonical AGENTS checks passed; it reports the repository's existing
  `scripts/hooks/pre-commit` layout as a `hook.script` warning because no
  `bin/pre-commit.sh` exists.
- `git diff --check` — passed.

### 2026-09-05 — Task 8 review corrections

Corrected the recovery gaps found in the first Task 8 implementation. Pi now
uses the durable previous host session path supplied to a fresh
`session_start` instance to resolve and flush the old knowledge buffer before
initializing the replacement session. Reloads also recover the current session
buffer before reinitialization. The one-hour orphan sweep remains a fallback,
not the primary replacement path.

Both TypeScript adapters retry a failed `session-append` immediately with the
same payload, so a one-shot transient failure does not require host event
redelivery. The adapter tests now use the real core append and flush scripts
behind failure-injecting wrappers, invoke each failed message exactly once,
and instantiate a fresh Pi adapter between failed shutdown and replacement
startup. The Pi replacement test covers the durable observation produced by
the recovered buffer.

Raised the declared Node engine floor in `package.json`, `package-lock.json`,
and the README to `>=22.19.0`, matching the pinned Pi SDK.

Verification:

- `npm run type-check` — passed.
- `npm test` — 7 adapter lifecycle tests passed.
- `just check` — ShellCheck and portability lint passed; TypeScript type-check
  passed; 342 Bats tests and 7 adapter lifecycle tests passed.

### 2026-09-06 — Task 8 core failure propagation correction

Fixed the failure boundary missed by the adapter recovery tests. `session-append`
now returns nonzero when JSONL persistence fails, and `session-flush` returns
nonzero when `observe` fails while retaining the buffer. The adapter fixture now
uses temporary permission changes to trigger those failures inside the real core
scripts, so retries are tested against actual persistence outcomes.

Added core-script regression tests for failed buffer writes and failed
observation writes. Existing OpenCode and Pi one-shot recovery tests now verify
the same real failure path through the adapter wrappers.

Verification:

- `just check` — ShellCheck and portability lint passed; TypeScript type-check
  passed; 344 Bats tests and 7 adapter lifecycle tests passed.

### 2026-09-06 — Task 8.5

Hardened lint target confinement before any target is read. Existing external
files and symlinks escaping `KB_CONTENT_DIR` now fail, with regression tests for
both cases. The real private content tree still has 37 historical missing
observation references across 11 articles. Documented a strict migration policy
that requires restoring evidence from content Git history or reviewing and
replacing/removing each stale source; tooling does not weaken validation or edit
private content.

Updated retrieval evaluation to distinguish unanswerable cases from false
positive retrieval, report aggregate false-positive metrics, and treat a new
false positive as a baseline regression. Added a public fixture with related
distractor evidence and regression coverage.

Typed adapter lifecycle fixtures against the pinned OpenCode and Pi SDK event,
part, message, handler, and context declarations. Documented at-least-once
append persistence and covered a post-write append failure that duplicates the
same transcript line after retry. Unified unset and `1` as enabled observation
capture and `0` as disabled across shell adapters, TypeScript adapters, skills,
README, and tests.

Verification:

- `just check` — ShellCheck and portability lint passed; pinned dependencies
  installed cleanly; TypeScript type-check passed; 348 Bats tests and 9
  adapter lifecycle tests passed.
- `npm run type-check` — passed after reinstalling the pinned dependencies.
- `npm test` — 9 adapter lifecycle tests passed. The adapter runner required
  the sandbox IPC workaround.
- `KB_CONTENT_DIR=content scripts/lint --path content/knowledge` — exit 1 as
  expected: 153 files, 37 historical missing-source errors, and 0 warnings.
- `git diff --check` — passed.

Remaining limitation: strict lint of the real private content tree is expected
to fail on the 37 documented historical references until a separate content
migration resolves them. Task 9, optional retrieval infrastructure, remains
pending and is not part of this implementation.
