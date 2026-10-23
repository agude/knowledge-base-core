# Bats tests not ported

Bats tests whose assertion is about how the Bash code works internally, not
about observable behavior: which tool or fallback it uses, scratch-file
allocation, or a `_lib.sh` function that no executable exposes. See
`plan.md`, step 1a. The behavior audit reviews every row.

| Bats file | Test | Reason |
|---|---|---|
