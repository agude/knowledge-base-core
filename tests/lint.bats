#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

GOOD='---
title: "Networking"
updated: 2026-08-08
verified: 2026-08-08
---

# Networking

## DNS

How DNS works.

## TLS

TLS overview.'

@test "lint passes a well-formed article" {
    create_test_article "net.md" "$GOOD"
    run "$SCRIPTS/lint"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"1 file(s): 0 error(s), 0 warning(s)"* ]]
}

@test "lint flags a second H1" {
    create_test_article "two.md" "$GOOD

# Second Title

## More

Content."
    run "$SCRIPTS/lint"
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"second H1"* ]]
}

@test "lint flags a file with no H1" {
    create_test_article "none.md" '---
title: "No Title"
updated: 2026-08-08
verified: 2026-08-08
---

## Section

Content.'
    run "$SCRIPTS/lint"
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"no H1"* ]]
}

@test "lint flags missing verified" {
    create_test_article "bare.md" '---
title: "Bare"
updated: 2026-08-08
---

# Bare

## Section

Content.'
    run "$SCRIPTS/lint"
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"missing verified"* ]]
}

@test "lint flags a malformed verified date" {
    create_test_article "baddate.md" '---
title: "Bad"
updated: 2026-08-08
verified: last Tuesday
---

# Bad

## Section

Content.'
    run "$SCRIPTS/lint"
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"not a YYYY-MM-DD date"* ]]
}

@test "lint flags an unclosed code fence" {
    create_test_article "open.md" '---
title: "Open"
updated: 2026-08-08
verified: 2026-08-08
---

# Open

## Section

```bash
echo hi'
    run "$SCRIPTS/lint"
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"unclosed code fence"* ]]
}

@test "lint does not count headings inside fences as H1s" {
    create_test_article "fenced.md" '---
title: "Fenced"
updated: 2026-08-08
verified: 2026-08-08
---

# Fenced

## Section

```bash
# a comment, not a second H1
echo hi
```'
    run "$SCRIPTS/lint"
    [[ "$status" -eq 0 ]]
}

@test "lint warns about an oversized H2 without failing" {
    long="$(printf 'filler\n%.0s' $(seq 60))"
    create_test_article "long.md" "---
title: \"Long\"
updated: 2026-08-08
verified: 2026-08-08
---

# Long

## Big Section

$long"
    run "$SCRIPTS/lint"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"H2 is"* ]]
    [[ "$output" == *"0 error(s), 1 warning(s)"* ]]
}

@test "lint --strict fails on warnings" {
    long="$(printf 'filler\n%.0s' $(seq 60))"
    create_test_article "long.md" "---
title: \"Long\"
updated: 2026-08-08
verified: 2026-08-08
---

# Long

## Big Section

$long"
    run "$SCRIPTS/lint" --strict
    [[ "$status" -eq 1 ]]
}

@test "lint --max-lines raises the threshold" {
    long="$(printf 'filler\n%.0s' $(seq 60))"
    create_test_article "long.md" "---
title: \"Long\"
updated: 2026-08-08
verified: 2026-08-08
---

# Long

## Big Section

$long"
    run "$SCRIPTS/lint" --max-lines 100
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"0 warning(s)"* ]]
}

@test "lint warns about duplicate H2 text" {
    create_test_article "dup.md" '---
title: "Dup"
updated: 2026-08-08
verified: 2026-08-08
---

# Dup

## Setup

First.

## Other

Middle.

## Setup

Second.'
    run "$SCRIPTS/lint"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"duplicate H2 text: Setup"* ]]
}

@test "lint --path scopes to a subdirectory" {
    create_test_article "ok.md" "$GOOD"
    create_test_article "bad/broken.md" '# Only

## Section

Content.'
    run "$SCRIPTS/lint" --path knowledge/bad
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"1 file(s)"* ]]
}

@test "lint accepts a single file" {
    create_test_article "net.md" "$GOOD"
    run "$SCRIPTS/lint" --file knowledge/net.md
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"1 file(s)"* ]]
}
