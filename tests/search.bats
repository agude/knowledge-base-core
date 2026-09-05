#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "search finds match in knowledge article" {
    create_test_article "topic.md" "---
title: Test
---

# Topic

## Section One

The server uses PostgreSQL for storage."
    run "$SCRIPTS/search" "PostgreSQL"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"knowledge/topic.md"* ]]
    [[ "$output" == *"Section One"* ]]
    [[ "$output" == *"PostgreSQL"* ]]
}

@test "search finds match in pending observations" {
    create_test_observation "20260412T000000-aaaa.md" "Test obs" "Found a bug in the deploy script."
    run "$SCRIPTS/search" "deploy script"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"observations/pending"* ]]
}

@test "search is case-insensitive" {
    create_test_article "topic.md" "# Topic

## Info

PostgreSQL is the database."
    run "$SCRIPTS/search" "postgresql"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"PostgreSQL"* ]]
}

@test "search returns nothing for no match" {
    create_test_article "topic.md" "# Topic

## Info

Some content."
    run "$SCRIPTS/search" "zzzznonexistent"
    [[ -z "$output" ]]
}

@test "search handles empty content directories" {
    run "$SCRIPTS/search" "anything"
    [[ "$status" -eq 0 ]]
}

@test "search works when first file has no match" {
    create_test_article "aaa-no-match.md" "# No Match

## Section

Nothing relevant here."
    create_test_article "zzz-has-match.md" "# Has Match

## Found It

The PostgreSQL server is running."
    run "$SCRIPTS/search" "PostgreSQL"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"zzz-has-match.md"* ]]
    [[ "$output" != *"aaa-no-match.md"* ]]
}

@test "search ANDs multiple terms within a file" {
    create_test_article "both.md" "# Both

## Info

The Synology NAS runs Docker."
    create_test_article "one.md" "# One

## Info

The Synology unit is upstairs."
    run "$SCRIPTS/search" synology docker
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"both.md"* ]]
    [[ "$output" != *"one.md"* ]]
}

@test "search prints every line matching any term" {
    create_test_article "both.md" "# Both

## Info

The Synology NAS is upstairs.
It runs Docker containers."
    run "$SCRIPTS/search" synology docker
    [[ "$output" == *"Synology NAS is upstairs"* ]]
    [[ "$output" == *"runs Docker containers"* ]]
}

@test "search treats a multi-word argument as one phrase" {
    create_test_article "phrase.md" "# Phrase

## Info

A Synology NAS lives here."
    create_test_article "split.md" "# Split

## Info

Synology makes it. A NAS is a NAS."
    run "$SCRIPTS/search" "synology nas"
    [[ "$output" == *"phrase.md"* ]]
    [[ "$output" != *"split.md"* ]]
}

@test "search rejects an unknown option instead of searching for it" {
    create_test_article "topic.md" "# Topic

## Info

Content."
    run "$SCRIPTS/search" --all
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Unknown option"* ]]
}

@test "search -- treats a leading-dash term literally" {
    create_test_article "flags.md" "# Flags

## Info

Never pass --no-verify to git commit."
    run "$SCRIPTS/search" -- --no-verify
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"flags.md"* ]]
}

@test "search with no terms exits nonzero" {
    run "$SCRIPTS/search"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Usage"* ]]
}

@test "search shows 'top' when match is before any H2" {
    create_test_article "topic.md" "---
title: \"Matched in frontmatter\"
---

# Topic

Preamble with target_word here."
    run "$SCRIPTS/search" "target_word"
    [[ "$output" == *"| top |"* ]]
}

@test "search ranks a title match above a body match" {
    create_test_article "exact.md" '---
title: "Bind Mounts on Synology"
updated: 2026-08-08
verified: 2026-08-08
---

# Bind Mounts on Synology

## Setup

Details.'
    create_test_article "passing.md" '---
title: "Home Lab Overview"
updated: 2026-08-08
verified: 2026-08-08
---

# Home Lab Overview

## Machines

One line mentions bind mounts in passing.'
    run "$SCRIPTS/search" --files "bind mounts"
    [[ "${lines[0]}" == *"exact.md"* ]]
    [[ "${lines[1]}" == *"passing.md"* ]]
}

@test "search ranks a heading match above a body match" {
    create_test_article "heading.md" "# A

## Docker networking

Content."
    create_test_article "body.md" "# B

## Other

We mention docker here in prose."
    run "$SCRIPTS/search" --files docker
    [[ "${lines[0]}" == *"heading.md"* ]]
}

@test "search never prints frontmatter lines as results" {
    create_test_article "fm.md" '---
title: "Postgres Notes"
updated: 2026-08-08
verified: 2026-08-08
---

# Postgres Notes

## Setup

The server runs Postgres.'
    run "$SCRIPTS/search" postgres
    [[ "$output" != *'title: "Postgres Notes"'* ]]
    [[ "$output" == *"The server runs Postgres"* ]]
}

@test "search caps output at --limit and says what it dropped" {
    for i in 1 2 3 4 5 6 7 8; do
        create_test_article "topic$i.md" "# Topic $i

## Section

A line about widgets here.
Another line about widgets.
A third widgets line.
A fourth widgets line."
    done
    run "$SCRIPTS/search" --limit 5 widgets
    matches=0
    for l in "${lines[@]}"; do
        [[ "$l" == *" | "* ]] && matches=$((matches + 1))
    done
    [[ "$matches" -eq 5 ]]
    # 8 files x 4 matching lines = 32; 5 shown, so 27 hidden. The count
    # has to be right, not merely present.
    [[ "$output" == *"27 more line(s)"* ]]
}

@test "search --limit 0 prints everything" {
    for i in 1 2 3 4 5 6 7 8; do
        create_test_article "topic$i.md" "# Topic $i

## Section

A line about widgets here."
    done
    run "$SCRIPTS/search" --limit 0 --per-file 0 widgets
    matches=0
    for l in "${lines[@]}"; do
        [[ "$l" == *" | "* ]] && matches=$((matches + 1))
    done
    [[ "$matches" -eq 8 ]]
}

@test "search caps lines from a single file with --per-file" {
    create_test_article "many.md" "# Many

## Section

widgets one
widgets two
widgets three
widgets four
widgets five"
    run "$SCRIPTS/search" --per-file 2 widgets
    matches=0
    for l in "${lines[@]}"; do
        [[ "$l" == *" | "* ]] && matches=$((matches + 1))
    done
    [[ "$matches" -eq 2 ]]
}

@test "search skips the archive unless asked" {
    mkdir -p "$TEST_CONTENT_DIR/observations/archived"
    cat > "$TEST_CONTENT_DIR/observations/archived/20260412T000000-cccc.md" <<'EOF'
---
title: "Old note"
---

Something about kubernetes.
EOF
    run "$SCRIPTS/search" kubernetes
    [[ -z "$output" ]]

    run "$SCRIPTS/search" --archive kubernetes
    [[ "$output" == *"observations/archived"* ]]
}

@test "search --archive includes open questions" {
    create_test_question "20260412T000000-dddd.md" "Who owns the kafka cluster?"
    run "$SCRIPTS/search" --archive kafka
    [[ "$output" == *"questions/open"* ]]
}

@test "search rejects a non-numeric limit" {
    run "$SCRIPTS/search" --limit lots widgets
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"take a number"* ]]
}

@test "search ignores headings inside code fences for section context" {
    create_test_article "fenced.md" '# Fenced

## Real Section

```bash
## not a heading
grep widgets file
```'
    run "$SCRIPTS/search" widgets
    [[ "$output" == *"| Real Section |"* ]]
    [[ "$output" != *"| not a heading |"* ]]
}

# --- regressions found by review ---

@test "search survives a filename containing a space" {
    create_test_article "docker.md" "# D

## S

docker notes"
    printf '# X\n\n## S\n\nx\n' > "$TEST_CONTENT_DIR/knowledge/has space.md"
    run "$SCRIPTS/search" docker
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"docker.md"* ]]
}

@test "search survives a filename containing a quote" {
    create_test_article "docker.md" "# D

## S

docker notes"
    printf '# X\n\n## S\n\nx\n' > "$TEST_CONTENT_DIR/knowledge/it's.md"
    run "$SCRIPTS/search" docker
    [[ "$output" == *"docker.md"* ]]
}

@test "search matches a term containing a backslash literally" {
    cat > "$TEST_CONTENT_DIR/knowledge/win.md" <<'EOF'
# W

## S

path C:\new\table here
EOF
    run "$SCRIPTS/search" 'C:\new'
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"win.md"* ]]
}

@test "search does not expand an escape sequence in a term" {
    printf '# T\n\n## S\n\nliteral a\tb\n' > "$TEST_CONTENT_DIR/knowledge/tab.md"
    run "$SCRIPTS/search" 'a\tb'
    [[ -z "$output" ]]
}

@test "search keeps fields apart when a heading contains a pipe" {
    create_test_article "pipe.md" "# P

## A | B

zebra here"
    run "$SCRIPTS/search" zebra
    [[ "$output" == *"| A | B | zebra here"* ]]
}

@test "search reports the true number of hidden lines and files" {
    for i in 1 2 3 4 5 6 7 8 9 10; do
        create_test_article "f$i.md" "# T$i

## S

needle here"
    done
    run "$SCRIPTS/search" --limit 4 needle
    [[ "$output" == *"6 more line(s)"* ]]
    [[ "$output" == *"6 unshown file(s)"* ]]
}

@test "search --files reports how many files it hid" {
    for i in 1 2 3 4 5 6; do
        create_test_article "f$i.md" "# T$i

## S

needle here"
    done
    run "$SCRIPTS/search" --files --limit 2 needle
    [[ "$output" == *"4 more file(s)"* ]]
}

@test "search honors fence length like the shared parser" {
    create_test_article "nested.md" '# N

## Real

````markdown
```
## not a heading
needle inside
```
````'
    run "$SCRIPTS/search" needle
    [[ "$output" == *"| Real |"* ]]
    [[ "$output" != *"not a heading"* ]]
}

@test "search default output labels freshness and uncurated evidence" {
    create_test_article "old.md" $'---\ntitle: "Old"\nverified: 2020-01-01\n---\n\n# Old\n\nneedle'
    create_test_observation "20260412T000000-eeee.md" "Pending" "needle"
    run "$SCRIPTS/search" --limit 2 needle
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"freshness=stale"* ]]
    [[ "$output" == *"pending observation; uncurated evidence"* ]]
}

@test "search text-only omits retrieval metadata" {
    create_test_article "old.md" $'---\ntitle: "Old"\nverified: 2020-01-01\n---\n\n# Old\n\nneedle'
    run "$SCRIPTS/search" --text-only needle
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"| top | needle"* ]]
    [[ "$output" != *"freshness="* ]]
}

@test "search JSON handles spaces, quotes, Unicode, and empty results" {
    create_test_article "résumé notes.md" $'---\ntitle: "Résumé Notes"\nverified: not-a-date\n---\n\n# Résumé Notes\n\n## Cité\n\nNeedle "quoted".'
    run "$SCRIPTS/search" --json needle
    [[ "$status" -eq 0 ]]
    json="$output"
    run jq -e '.results[0].path == "knowledge/résumé notes.md" and .results[0].text == "Needle \"quoted\"." and .results[0].freshness.status == "invalid" and .results[0].locator.section == "Cité" and .truncated == false' <<<"$json"
    [[ "$status" -eq 0 ]]

    run "$SCRIPTS/search" --json absent
    [[ "$status" -eq 0 ]]
    run jq -e '.results == [] and .returned == 0 and .truncated == false' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "search JSON reports source and archive provenance" {
    mkdir -p "$TEST_CONTENT_DIR/sources" "$TEST_CONTENT_DIR/observations/archived"
    cat > "$TEST_CONTENT_DIR/sources/manual.md" <<'EOF'
---
title: "Manual"
canonical: "https://example.test/manual"
synced: 2026-09-05
---

# Manual

needle
EOF
    cat > "$TEST_CONTENT_DIR/observations/archived/old.md" <<'EOF'
---
title: "Old"
disposition: duplicate
destination: knowledge/manual.md#Setup
---

# Old

needle
EOF
    run "$SCRIPTS/search" --json --archive needle
    [[ "$status" -eq 0 ]]
    json="$output"
    run jq -e '[.results[] | select(.corpus == "source document") | .provenance.references[0]] | index("https://example.test/manual") != null' <<<"$json"
    [[ "$status" -eq 0 ]]
    run jq -e '[.results[] | select(.corpus == "archive") | .provenance.disposition] | index("duplicate") != null' <<<"$json"
    [[ "$status" -eq 0 ]]
}

@test "search JSON keeps truncation diagnostics off stdout" {
    for i in 1 2 3; do
        create_test_article "topic$i.md" $'# Topic '"$i"$'\n\nneedle'
    done
    stderr_file="$TEST_CONTENT_DIR/search.stderr"
    json="$($SCRIPTS/search --json --limit 1 needle 2>"$stderr_file")"
    [[ "$?" -eq 0 ]]
    run jq -e '.truncated == true and .returned == 1' <<<"$json"
    [[ "$status" -eq 0 ]]
    stderr="$(<"$stderr_file")"
    [[ "$stderr" == *"hidden"* ]]
}

@test "search caps provenance references and reports the complete count" {
    create_test_article "many-sources.md" $'---\ntitle: "Many Sources"\nverified: 2026-01-01\nsources:\n  - observations/evidence-1.md\n  - observations/evidence-2.md\n  - observations/evidence-3.md\n  - observations/evidence-4.md\n  - observations/evidence-5.md\n  - observations/evidence-6.md\n  - observations/evidence-7.md\n---\n\n# Many Sources\n\nneedle'
    run "$SCRIPTS/search" --json needle
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].provenance | (.references | length == 5) and .reference_count == 7 and .references_truncated == true' <<<"$output"
    [[ "$status" -eq 0 ]]

    run "$SCRIPTS/search" needle
    [[ "$output" == *"+2 more"* ]]
}

@test "search reports open questions as question records" {
    create_test_question "20260412T000000-eeee.md" "Who owns the kafka cluster?"
    run "$SCRIPTS/search" --json --archive kafka
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].corpus == "question" and .results[0].provenance.state == "open" and .results[0].provenance.label == "unresolved knowledge gap"' <<<"$output"
    [[ "$status" -eq 0 ]]
}
