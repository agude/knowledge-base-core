# Bats tests not ported

Bats tests whose assertion is about how the Bash code works internally, not
about observable behavior: which tool or fallback it uses, scratch-file
allocation, or a `_lib.sh` function that no executable exposes. See
`plan.md`, step 1a. The behavior audit reviews every row.

| Bats file | Test | Reason |
|---|---|---|
| `doctor.bats` | doctor fails retrieval when date parsing returns no value | Probes the host `date` for the Bash runtime's freshness parsing; the Python runtime parses dates itself, and step 5 replaces the probe. |
| `doctor.bats` | doctor fails retrieval when sort features are unavailable | Probes `sort -z` and `sort -V` for the Bash runtime; step 5 replaces the probe. |
| `doctor.bats` | doctor makes a missing retrieval JSON encoder dependency fatal | Probes `od`, which only the Bash JSON encoder uses; step 5 replaces the probe. |
| `adapters.bats` | Claude retries an append that fails before persistence | Replaces the sibling `session-append` with a stub to count subprocess retries; the Python adapters append in-process (plan 3.5). Retry semantics are A-021. |
| `adapters.bats` | Claude preserves a duplicate after a post-persistence append failure | Same stub; asserts the retry's effect on a failed subprocess. A-021. |
| `adapters.bats` | Codex retries an append that fails before persistence | Same stub as the Claude retry test. A-021. |
| `adapters.bats` | Codex preserves a duplicate after a post-persistence append failure | Same stub as the Claude duplicate test. A-021. |
| `adapters.bats` | enabled adapters report message allocation and extraction failures | Injects failures into `mktemp` and `jq` through `PATH` stubs; asserts how the Bash adapters handle those tools failing. |
| `lib.bats` | every script that sources _lib.sh sets REPO_ROOT first | A static check of Bash source order. |
| `lib.bats` | string byte counts preserve locale and match file counts | Tests `byte_count_text` and its `LC_ALL` handling directly. Byte budgets are pinned through `search --max-bytes` and `pending --preview --max-bytes`. |
| `lib.bats` | sha256_file falls back to shasum | Tests the Bash fallback from `sha256sum` to `shasum`. |
| `lib.bats` | streaming JSON encoder propagates partial upstream failure without pipefail | Injects an `od` failure into the Bash JSON encoder. |
| `lib.bats` | metadata cache restores selected sections and full articles without rereading | Tests the Bash metadata cache's internal variables. Retrieval results are pinned through `search` and `section`. |
| `lib.bats` | retrieval loads article state once before lazy section parsing | Tests the Bash cache's laziness by stubbing internal functions. |
| `lib.bats` | article cache preserves interleaved question and archive provenance | Tests the Bash cache's internal variables. Provenance is pinned through `search` and `section` output. |
| `section.bats` | section text budgets clean scratch files after finalizer write failures | Injects a `cp` failure into the Bash budget finalizer. Scratch cleanup after normal truncated runs is pinned by `test_section.py::test_text_budget_truncates_and_cleans_up`. |
| `session_core.bats` | session-append does not append when od is missing | Removes `od`, which only the Bash JSON encoder uses. |
| `session_core.bats` | session-append does not append partial output from a failing od | Injects an `od` failure into the Bash JSON encoder. |
| `session_core.bats` | session-flush keeps the buffer when interrupted during observation writing | Stubs `cat` to pause inside the Bash observation writer. Interruption is pinned by `test_flush_interrupted_while_blocked` and `test_flush_interrupted_during_commit`. |
| `session_core.bats` | session-flush retains evidence when the observation body copy fails | Stubs `cat` to fail inside the Bash observation writer. |
| `search.bats` | search reports a parser failure instead of a false zero result | Replaces `awk`, the Bash search parser, with a failing stub. |
