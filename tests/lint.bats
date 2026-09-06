#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

commit_pending_observation() {
    (
        cd "$TEST_CONTENT_DIR"
        git add observations/pending
        git commit -q -m "add test observation"
    )
}

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

@test "lint validates relative links, anchors, and source references" {
    create_test_article "target.md" '---
title: "Target"
updated: 2026-08-08
verified: 2026-08-08
---

# Target

## Details

Content.'
    mkdir -p "$TEST_CONTENT_DIR/observations/archived"
    printf '%s\n' 'archived evidence' \
        > "$TEST_CONTENT_DIR/observations/archived/evidence.md"
    create_test_article "linked.md" '---
title: "Linked"
updated: 2026-08-08
verified: 2026-08-08
sources:
  - observations/archived/evidence.md
---

# Linked

## Links

[Target](target.md#details), [angle](<target.md>), and [external](https://example.com/missing.md).
'
    run "$SCRIPTS/lint" --file knowledge/linked.md
    [[ "$status" -eq 0 ]]
}

@test "lint flags missing links, anchors, and source references" {
    create_test_article "broken.md" '---
title: "Broken"
updated: 2026-08-08
verified: 2026-08-08
sources:
  - observations/archived/moved.md
---

# Broken

## Links

[Missing](missing.md) and [wrong anchor](broken.md#not-a-heading).
[Moved](moved.md).
'
    create_test_article "moved.md" "$GOOD"
    mv "$TEST_CONTENT_DIR/knowledge/moved.md" \
        "$TEST_CONTENT_DIR/knowledge/renamed.md"
    run "$SCRIPTS/lint" --file knowledge/broken.md
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"missing local source reference"* ]]
    [[ "$output" == *"missing local Markdown link target"* ]]
    [[ "$output" == *"missing local Markdown link anchor"* ]]
}

@test "lint ignores external URLs and fenced examples" {
    create_test_article "fenced-links.md" '---
title: "Fenced Links"
updated: 2026-08-08
verified: 2026-08-08
---

# Fenced Links

## Examples

```markdown
[Missing](missing.md)
```

[External](https://example.com/missing.md)

`[Inline example](missing-inline.md)`
'
    run "$SCRIPTS/lint" --file knowledge/fenced-links.md
    [[ "$status" -eq 0 ]]
}

@test "lint accepts a selected pending observation as a future archive source" {
    create_test_observation "selected.md" "Selected" "Evidence"
    commit_pending_observation
    batch_id="$($SCRIPTS/batch start | sed -n 's/^Created batch: //p')"
    create_test_article "pending-source.md" '---
title: "Pending Source"
updated: 2026-08-08
verified: 2026-08-08
sources:
  - observations/archived/selected.md
---

# Pending Source

## Claim

Claim.'

    run "$SCRIPTS/lint" --batch "$batch_id" --file knowledge/pending-source.md
    [[ "$status" -eq 0 ]]

    run "$SCRIPTS/lint" --file knowledge/pending-source.md
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"missing local source reference"* ]]

    "$SCRIPTS/archive" --batch "$batch_id" --disposition incorporated \
        --destination knowledge/pending-source.md#Claim selected.md --no-commit
    run "$SCRIPTS/lint" --file knowledge/pending-source.md
    [[ "$status" -eq 0 ]]
}

@test "lint rejects a deferred observation used as a future archive source" {
    create_test_observation "deferred.md" "Deferred" "Evidence"
    commit_pending_observation
    batch_id="$($SCRIPTS/batch start | sed -n 's/^Created batch: //p')"
    "$SCRIPTS/batch" defer "$batch_id" deferred.md
    create_test_article "deferred-source.md" '---
title: "Deferred Source"
updated: 2026-08-08
verified: 2026-08-08
sources:
  - observations/archived/deferred.md
---

# Deferred Source

## Claim

Claim.'

    run "$SCRIPTS/lint" --batch "$batch_id" --file knowledge/deferred-source.md
    [[ "$status" -eq 1 ]]
    [[ "$output" == *"missing local source reference"* ]]
}

@test "correction fixture preserves superseded evidence and canonical reason" {
    fixture="$BATS_TEST_DIRNAME/fixtures/lint/corrections"
    cp -R "$fixture/knowledge/." "$TEST_CONTENT_DIR/knowledge/"
    cp -R "$fixture/observations/." "$TEST_CONTENT_DIR/observations/"

    run "$SCRIPTS/lint" --path "$TEST_CONTENT_DIR/knowledge"
    [[ "$status" -eq 0 ]]
    grep -q 'Effective 2026-09-01' \
        "$TEST_CONTENT_DIR/knowledge/corrections.md"
    grep -q 'Retained old evidence' \
        "$TEST_CONTENT_DIR/knowledge/corrections.md"
    grep -q 'Reason: authoritative roster' \
        "$TEST_CONTENT_DIR/knowledge/corrections.md"
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
