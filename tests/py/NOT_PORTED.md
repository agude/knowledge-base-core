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
