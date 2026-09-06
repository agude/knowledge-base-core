# Knowledge Base Reliability and Retrieval Plan

Created: 2026-09-04. Status: tasks 1–4 implemented; tasks 5–9 pending.

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
| 9. Evaluate optional retrieval infrastructure | Conditional | 4, 5 |

Implement tasks 1–8. Task 9 requires a documented decision; adopting additional
infrastructure is conditional on measured failures and improvement.

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

- [ ] Document comparison of source authority, observation date, and effective
  date when a new observation contradicts an existing claim. Newer capture alone
  does not automatically establish authority.
- [ ] A worked fixture shows a corrected canonical claim, retained old evidence,
  and a recorded reason/effective date for supersession.
- [ ] An unresolved conflict remains explicitly labeled; curation does not
  manufacture agreement or mark conflicting claims verified.
- [ ] Partial article updates do not imply unrelated claims were reverified.
- [ ] Lint checks local Markdown links and `sources` references for missing files
  and, where supported, missing anchors. Define supported Markdown link forms.
- [ ] Relative links, moved articles, fenced examples, and external URLs have
  tests. Structural lint does not fetch external URLs.
- [ ] Batch validation accommodates references to observations being archived
  within the same curation transaction and rejects broken final references.
- [ ] Real content is not mass-edited to satisfy the new checks; document any
  compatibility findings for a separate curation pass.

## 7. Make the Manual Curation Queue Actionable

**Gap:** Startup counts show workload size but do not identify useful batches or
how much transcript review produces durable knowledge.

**Acceptance criteria**

- [ ] Add an explicit preview command or mode showing oldest pending age,
  observation versus transcript counts, input volume, and available topic hints.
- [ ] Topic hints are identified as hints; generating the preview needs no LLM.
- [ ] Batch completion reports disposition totals, destinations, and deferred
  work using task 1's persisted state.
- [ ] Empty queues, malformed metadata, and large transcripts have bounded,
  understandable output and tests.
- [ ] Detailed previews are requested explicitly rather than injected into every
  session. Existing compact startup counts remain available.
- [ ] Document how to prioritize stale articles that were recently retrieved.
  Access telemetry is optional: if added, keep it local, bounded, separate from
  content Git history, and independent of `verified` dates.
- [ ] No unattended curation or scheduled model calls are introduced.

## 8. Correct Documentation and Test Adapters

**Findings:** README setup conflates tooling and content roots. The knowledge-base
skill says default search covers curated articles only, although code includes
sources and pending observations. OpenCode/Pi tests check source strings; CI does
not type-check or execute those TypeScript adapters.

**Start with:** `README.md`, both portable skills, `scripts/install`,
`scripts/adapters/`, `tests/adapters.bats`, `tests/portability.bats`, and
`.github/workflows/test.yml`.

**Acceptance criteria**

- [ ] README examples distinguish tooling root from content root and work in a
  temporary installation with content outside the tooling checkout.
- [ ] Skills, help, and README agree on search corpora, output metadata, sync
  failures, batch archiving, and correction handling.
- [ ] Type-check OpenCode and Pi adapters against documented, reproducibly
  installed SDK versions. Verify current host contracts against primary sources.
- [ ] Execute adapter lifecycle tests with mocked host events and temporary
  storage: start, capture, duplicate events, switch/fork where supported,
  disabled observation, failed capture, and shutdown/flush recovery.
- [ ] Tests establish behavior rather than merely checking event names in source.
- [ ] Preserve existing shell-adapter behavior and core session tests.
- [ ] CI runs the adapter checks, Bats suite, ShellCheck, and portability lint.
  Load project-standards and readable-code skills before tooling/code changes.
- [ ] Identify stale repo-mechanics claims encountered in sampled KB articles for
  later curation; keep the repository as the authority for implementation details.

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

- [ ] Tasks 1–8 meet their acceptance criteria; task 9 has a recorded decision.
- [ ] Run targeted checks as changes land, then the complete required suite.
  Record actual commands and results; do not reuse historical test counts.
- [ ] Review the final diff for unrelated changes and private content leakage.
- [ ] Document command compatibility changes and migration requirements.
- [ ] Record any remaining limitations with evidence and affected task IDs.
- [ ] Update this plan so another session can distinguish completed, deferred,
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
