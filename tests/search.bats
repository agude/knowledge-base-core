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
    [[ "$output" == *"more line(s)"* ]]
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
