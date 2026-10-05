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

@test "search reports a parser failure instead of a false zero result" {
    create_test_article "topic.md" "# Topic

needle"
    fake_bin="$TEST_CONTENT_DIR/fake-bin"
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\nprintf "forced parser failure\\n" >&2\nexit 42\n' > "$fake_bin/awk"
    chmod +x "$fake_bin/awk"
    run env PATH="$fake_bin:$PATH" "$SCRIPTS/search" needle
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Search failed while reading"* ]]
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
    run "$SCRIPTS/search" --json "target_word"
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].locator.section == "top" and .results[0].locator.number == null and .results[0].locator.command == "--top"' <<<"$output"
    [[ "$status" -eq 0 ]]
    run "$SCRIPTS/section" --text-only --file knowledge/topic.md --top
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Preamble with target_word here."* ]]

    run "$SCRIPTS/search" "target_word"
    [[ "$output" == *"| top |"* ]]
    [[ "$output" == *"section-command=--top"* ]]
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

@test "search ranks an exact title above repeated body mentions" {
    create_test_article "exact.md" '---
title: "Bind Mounts"
---

# Notes

Documentation.'
    create_test_article "repeated.md" '# Repeated

## Notes

bind mounts
bind mounts
bind mounts
bind mounts
bind mounts'
    run "$SCRIPTS/search" --json --limit 2 --per-file 0 "bind mounts"
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].path == "knowledge/exact.md" and .results[0].locator.section == "title" and .results[0].locator.number == null and .results[0].locator.command == "--title"' <<<"$output"
    [[ "$status" -eq 0 ]]

    run "$SCRIPTS/section" --text-only --file knowledge/exact.md --title
    [[ "$status" -eq 0 ]]
    [[ "$output" == "Bind Mounts" ]]

    run "$SCRIPTS/search" --limit 1 "bind mounts"
    [[ "$output" == *"section-command=--title"* ]]
}

@test "search counts repeated identical evidence once" {
    create_test_article "repeated.md" '# Repeated

## Notes

same evidence
same evidence
same evidence'
    run "$SCRIPTS/search" --json --per-file 0 "same evidence"
    [[ "$status" -eq 0 ]]
    run jq -e '(.results[0].match_count == 1) and (.results | length == 1)' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "search ranks a section containing all terms above file-level fallback" {
    create_test_article "split.md" '# Split

## First

alpha

## Second

beta'
    create_test_article "complete.md" '# Complete

## All terms

alpha beta'
    run "$SCRIPTS/search" --json --limit 0 --per-file 0 alpha beta
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].path == "knowledge/complete.md" and .results[0].locator.section == "All terms"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "search ranks complete coverage above title and heading fallback" {
    create_test_article "title-heading-fallback.md" '---
title: "alpha"
---

# Notes

## beta

The terms are split between the title and heading.'
    create_test_article "complete.md" '# Complete

## Unrelated

alpha beta'
    run "$SCRIPTS/search" --json --limit 0 --per-file 0 alpha beta
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].path == "knowledge/complete.md" and .results[0].locator.section == "Unrelated"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "search exposes H2 numbers for duplicate headings" {
    create_test_article "duplicate.md" '# Duplicate

## Same heading

first needle

## Same heading

second needle'
    run "$SCRIPTS/search" --json --limit 0 --per-file 0 needle
    [[ "$status" -eq 0 ]]
    run jq -e '(.results | length == 2) and
        .results[0].locator.section == "Same heading" and
        .results[0].locator.number == "1" and
        .results[1].locator.number == "2"' <<<"$output"
    [[ "$status" -eq 0 ]]

    run "$SCRIPTS/search" --limit 0 --per-file 0 needle
    [[ "$output" == *"[section-number=1]"* ]]
    [[ "$output" == *"[section-number=2]"* ]]

    run "$SCRIPTS/section" --text-only --file knowledge/duplicate.md --number 2
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"second needle"* ]]
    [[ "$output" != *"first needle"* ]]
}

@test "search excerpt selects the strongest evidence line" {
    create_test_article "excerpt.md" '# Excerpt

## Notes

relevant
context
relevant context is the useful evidence
other relevant line'
    run "$SCRIPTS/search" --json --per-file 0 relevant context
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].text | contains("relevant context is the useful evidence")' <<<"$output"
    [[ "$status" -eq 0 ]]
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
    # Each file now contributes one ranked section result.
    [[ "$output" == *"3 more result section(s)"* ]]
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

@test "search caps sections from a single file with --per-file" {
    create_test_article "many.md" "# Many

## First

widgets one

## Second

widgets two

## Third

widgets three"
    run "$SCRIPTS/search" --per-file 2 --limit 0 widgets
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

@test "search rejects an invalid byte budget" {
    run "$SCRIPTS/search" --max-bytes nope widgets
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"--max-bytes takes a non-negative number"* ]]
}

@test "search treats leading-zero byte budgets as decimal" {
    create_test_article "budget.md" '# Budget

needle'
    run "$SCRIPTS/search" --json --max-bytes 01000 needle
    [[ "$status" -eq 0 ]]
    run jq -e '.max_bytes == 1000' <<<"$output"
    [[ "$status" -eq 0 ]]
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
    [[ "$output" == *"6 more result section(s)"* ]]
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

@test "search exposes unresolved conflicts separately from freshness" {
    fixture="$BATS_TEST_DIRNAME/fixtures/lint/corrections"
    cp -R "$fixture/knowledge/." "$TEST_CONTENT_DIR/knowledge/"
    cp -R "$fixture/observations/." "$TEST_CONTENT_DIR/observations/"

    run "$SCRIPTS/search" --json --limit 1 "team message"
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].freshness.status == "fresh" and .results[0].conflict.status == "unresolved"' <<<"$output"
    [[ "$status" -eq 0 ]]

    run "$SCRIPTS/search" --limit 1 "team message"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"freshness=fresh"* ]]
    [[ "$output" == *"conflict=unresolved"* ]]
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
    run jq -e '.results[0].path == "knowledge/résumé notes.md" and .results[0].text == "Needle \"quoted\"." and .results[0].freshness.status == "invalid" and .results[0].locator.section == "Cité" and .results[0].locator.number == "1" and .truncated == false' <<<"$json"
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

@test "search path and topic filters scope knowledge results" {
    create_test_article "projects/tool.md" '# Tool

## Build

project-only needle'
    create_test_article "home.md" '# Home

## Notes

other needle'

    run "$SCRIPTS/search" --path knowledge/projects needle
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"knowledge/projects/tool.md"* ]]
    [[ "$output" != *"knowledge/home.md"* ]]

    run "$SCRIPTS/search" --topic projects needle
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"knowledge/projects/tool.md"* ]]
    [[ "$output" != *"knowledge/home.md"* ]]
}

@test "search corpus filter selects only the requested corpus" {
    create_test_article "article.md" '# Article

needle'
    cat > "$TEST_CONTENT_DIR/sources/manual.md" <<'EOF'
---
title: "Manual"
synced: 2026-09-05
---

# Manual

needle
EOF
    run "$SCRIPTS/search" --corpus sources needle
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"sources/manual.md"* ]]
    [[ "$output" != *"knowledge/article.md"* ]]
}

@test "search normalizes a relative content root" {
    create_test_article "relative.md" '# Relative

needle'
    run sh -c 'cd "$1" && KB_CONTENT_DIR="$2" "$3" needle' sh "$(dirname "$TEST_CONTENT_DIR")" "$(basename "$TEST_CONTENT_DIR")" "$SCRIPTS/search"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"knowledge/relative.md"* ]]
}

@test "question search normalizes prose while preserving commands dates and paths" {
    create_test_article "question.md" '# Question

## Evidence

restart --no-verify on 2026-10-03 from /srv/backups/kb; keep not current.'
    run "$SCRIPTS/search" --query 'How do I restart --no-verify on 2026-10-03 from /srv/backups/kb?'
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"question.md"* ]]
    [[ "$output" == *"query-mode=question"* ]]
}

@test "question normalization preserves short flags and negation" {
    source "$SCRIPTS/_lib.sh"
    run question_terms "How do I run tool -s? Why doesn't this work?"
    [[ "$status" -eq 0 ]]
    [[ "$output" == $'run\ntool\n-s\ndoesn\x27t\nwork' ]]
}

@test "question search strips wrapping quotes but preserves internal apostrophes" {
    create_test_article "quotes.md" '# Quotes

## Evidence

needle'

    run "$SCRIPTS/search" --query "Where is 'needle'?"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"quotes.md"* ]]

    source "$SCRIPTS/_lib.sh"
    run question_terms "Where is 'needle'? Why doesn't this work?"
    [[ "$status" -eq 0 ]]
    [[ "$output" == $'needle\ndoesn\x27t\nwork' ]]
}

@test "question search strips quotes spanning a phrase" {
    create_test_article "command-phrase.md" '# Command phrase

## Evidence

The service restarts with systemctl restart kb-api.'

    run "$SCRIPTS/search" --query "What is 'systemctl restart kb-api'?"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"command-phrase.md"* ]]

    source "$SCRIPTS/_lib.sh"
    run question_terms "What is 'systemctl restart kb-api'?"
    [[ "$status" -eq 0 ]]
    [[ "$output" == $'systemctl\nrestart\nkb-api' ]]
}

@test "question search strips sentence punctuation without losing dotted identifiers" {
    create_test_article "punctuation.md" '# Punctuation

## Evidence

Backups live at /srv/backups/kb. The API hostname is api.internal.example.'
    run "$SCRIPTS/search" --query 'Where are the backups.'
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"punctuation.md"* ]]

    run "$SCRIPTS/search" --query 'What is the API hostname.'
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"punctuation.md"* ]]
}

@test "question search preserves non-ASCII searchable terms" {
    create_test_article "unicode.md" '# Résumé

## État

The résumé status is current.'
    run "$SCRIPTS/search" --query 'What is the résumé status?'
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"unicode.md"* ]]
}

@test "question search rejects an all-stopword question" {
    run "$SCRIPTS/search" --query 'how do I'
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"no searchable terms"* ]]
}

@test "question and literal search modes cannot be combined" {
    run "$SCRIPTS/search" --query 'find this' literal
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"cannot be combined"* ]]
}

@test "question relaxation is opt in and ranks complete coverage first" {
    create_test_article "partial.md" '# Partial

## Evidence

restart service'
    create_test_article "complete.md" '# Complete

## Evidence

restart api database'
    run "$SCRIPTS/search" --query 'how restart api database tunnel' --json
    [[ "$status" -eq 0 ]]
    run jq -e '.results | length == 0' <<<"$output"
    [[ "$status" -eq 0 ]]

    run "$SCRIPTS/search" --query 'how restart api database tunnel' --relax --json --limit 0
    [[ "$status" -eq 0 ]]
    run jq -e '.match_mode == "relaxed" and .results[0].path == "knowledge/complete.md"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "question aliases produce an explicit routing result" {
    create_test_article "network.md" $'---\ntitle: "WireGuard"\naliases:\n  - "production tunnel"\n---\n# Network\n\n## Peers\n\nThe peer is wg-kb-prod.'
    run "$SCRIPTS/search" --query 'where is the production tunnel' --json
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].routing == true and
        .results[0].locator.command == "--alias" and
        .results[0].alias == "production tunnel" and
        .results[0].text == "production tunnel"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "question aliases do not promote partial body evidence to strict evidence" {
    create_test_article "network.md" $'---\ntitle: "WireGuard"\naliases:\n  - "production tunnel"\n---\n# Network\n\n## Billing\n\nProduction billing uses a separate account.'
    run "$SCRIPTS/search" --query 'where is the production tunnel' --json
    [[ "$status" -eq 0 ]]
    run jq -e '.results | length == 1 and .[0].routing == true and .[0].locator.command == "--alias" and .[0].match_mode == "strict"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "question explanation stays on stderr and preserves JSON stdout" {
    create_test_article "explain.md" '# Explain

## Evidence

restart api'
    run bash -c '"$1" --query "how restart api" --explain --json >"$2" 2>"$3"' \
        _ "$SCRIPTS/search" "$TEST_CONTENT_DIR/out.json" "$TEST_CONTENT_DIR/explain.log"
    [[ "$status" -eq 0 ]]
    run jq -e '.query == "how restart api" and .query_terms == ["restart", "api"]' \
        "$TEST_CONTENT_DIR/out.json"
    [[ "$status" -eq 0 ]]
    grep -q 'original query: how restart api' "$TEST_CONTENT_DIR/explain.log"
}

@test "search explanation reports emitted records after the JSON byte budget" {
    for i in 1 2 3; do
        create_test_article "budget-explain-$i.md" "# Budget Explain $i

## Evidence

budget-explain-needle $i"
    done
    one_result="$TEST_CONTENT_DIR/one-result.json"
    "$SCRIPTS/search" --json --limit 1 --per-file 0 budget-explain-needle > "$one_result"
    cap="$(wc -c < "$one_result" | tr -d '[:space:]')"
    cap=$((cap + 100))

    run bash -c '"$1" --json --limit 0 --per-file 0 --max-bytes "$2" \
        --explain budget-explain-needle >"$3" 2>"$4"' \
        _ "$SCRIPTS/search" "$cap" "$TEST_CONTENT_DIR/budget.json" \
        "$TEST_CONTENT_DIR/budget.explain"
    [[ "$status" -eq 0 ]]
    run jq -e '.returned == 1 and .total_lines == 3 and .omitted_results == 2' \
        "$TEST_CONTENT_DIR/budget.json"
    [[ "$status" -eq 0 ]]
    grep -q 'candidates: 3; returned: 1' "$TEST_CONTENT_DIR/budget.explain"
    grep -q 'omissions: result/per-file=0; byte-budget=2' "$TEST_CONTENT_DIR/budget.explain"
}

@test "search text explanations count result records across output modes" {
    for i in 1 2 3; do
        create_test_article "combined-limit-$i.md" "# Combined Limit $i

## Evidence

combined-limit-needle $i"
    done

    for mode in normal text-only files; do
        mode_args=()
        case "$mode" in
            text-only) mode_args+=(--text-only) ;;
            files) mode_args+=(--files) ;;
        esac
        explain_file="$TEST_CONTENT_DIR/$mode.explain"
        run bash -c '"$1" --limit 1 --max-bytes 10000 --explain "${@:4}" \
            >"$2" 2>"$3"' _ "$SCRIPTS/search" \
            "$TEST_CONTENT_DIR/$mode.out" "$explain_file" \
            "${mode_args[@]}" combined-limit-needle
        [[ "$status" -eq 0 ]]
        grep -q 'candidates: 3; returned: 1' "$explain_file"
    done
}

@test "search JSON includes section metadata for section results" {
    create_test_article "section-metadata.md" $'---\ntitle: "Section Metadata"\nverified: 2026-10-03\n---\n\n# Section Metadata\n\n## Current\n\n<!-- kb-section: verified=2026-10-03; status=current; supersedes=2 -->\nCurrent guidance.\n\n## Historical\n\n<!-- kb-section: verified=2026-01-01; status=superseded; sources=observations/archived/old.md -->\nHistorical guidance.'
    run env FRESHNESS_TODAY_EPOCH=1790985600 "$SCRIPTS/search" --json historical guidance
    [[ "$status" -eq 0 ]]
    run jq -e '.results[0].section_metadata.status == "superseded" and .results[0].section_metadata.source_scope == "section" and .results[0].provenance.scope == "section" and .results[0].freshness.status == "stale"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "search uses matched H3 metadata instead of its H2 parent metadata" {
    fixture="$BATS_TEST_DIRNAME/fixtures/section-metadata"
    cp "$fixture/knowledge/metadata.md" "$TEST_CONTENT_DIR/knowledge/"
    cp -R "$fixture/observations/." "$TEST_CONTENT_DIR/observations/"
    run env FRESHNESS_TODAY_EPOCH=1790985600 "$SCRIPTS/search" --json \
        --limit 0 --per-file 0 "Inherited section metadata"
    [[ "$status" -eq 0 ]]
    run jq -e '.results | length == 1 and
        .[0].locator.number == "2.1" and
        .[0].section_metadata.status == "superseded" and
        .[0].freshness.status == "stale" and
        .[0].conflict.status == "none"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "search keeps section metadata isolated when result files interleave" {
    create_test_article "a.md" $'---\ntitle: "Article A"\nverified: 2026-10-03\nttl: domain\nstatus: current\nsources:\n  - observations/archived/a.md\n---\n\n# Article A\n\n## Needle\n\nneedle\n\n## History\n\nneedle'
    create_test_article "b.md" $'---\ntitle: "Article B"\nverified: 2025-01-01\nttl: domain\nstatus: superseded\nsources:\n  - observations/archived/b.md\n---\n\n# Article B\n\n## Notes\n\nneedle\nanother needle'

    run "$SCRIPTS/search" --json --limit 0 --per-file 0 needle
    [[ "$status" -eq 0 ]]
    run jq -e '.results | length == 3 and
        .[0].path == "knowledge/a.md" and .[0].locator.number == "1" and
        .[0].freshness.value == "2026-10-03" and
        .[0].section_metadata.status == "current" and
        .[1].path == "knowledge/b.md" and .[1].locator.number == "1" and
        .[1].freshness.value == "2025-01-01" and
        .[1].section_metadata.status == "superseded" and
        .[2].path == "knowledge/a.md" and .[2].locator.number == "2" and
        .[2].freshness.value == "2026-10-03" and
        .[2].section_metadata.status == "current" and
        .[2].provenance.references[0] == "observations/archived/a.md"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "search JSON byte budgets retain complete records" {
    create_test_article "budget.md" '# Budget

## Evidence

budget needle with enough metadata to make the response larger than its envelope.'
    create_test_article "budget-two.md" '# Budget Two

## Evidence

budget needle with enough metadata to make the response larger than its envelope.'
    full_file="$TEST_CONTENT_DIR/full.json"
    "$SCRIPTS/search" --json --limit 0 needle >"$full_file"
    full_bytes="$(wc -c < "$full_file" | tr -d '[:space:]')"
    cap=$((full_bytes - 1))
    run "$SCRIPTS/search" --json --limit 0 --max-bytes "$cap" needle
    [[ "$status" -eq 0 ]]
    output_bytes="$(printf '%s\n' "$output" | wc -c | tr -d '[:space:]')"
    (( output_bytes <= cap ))
    [[ "$output" == *'"truncated":true'* ]]
    [[ "$output" == *'"omitted_results":1'* ]]
}

@test "search JSON budgets report records hidden by result limits" {
    create_test_article "budget-one.md" '# Budget One

## Evidence

budget-limit-needle'
    create_test_article "budget-two.md" '# Budget Two

## Evidence

budget-limit-needle'
    run bash -c '"$1" --json --limit 1 --max-bytes 20000 budget-limit-needle >"$2" 2>"$3"' \
        _ "$SCRIPTS/search" "$TEST_CONTENT_DIR/out.json" "$TEST_CONTENT_DIR/out.err"
    [[ "$status" -eq 0 ]]
    run jq -e '.returned == 1 and .total_lines == 2 and .truncated == true and .omitted_results == 1' \
        "$TEST_CONTENT_DIR/out.json"
    [[ "$status" -eq 0 ]]
}

@test "search text byte budgets preserve unbounded output and omission counts" {
    create_test_article "budget-summary.md" '# Budget Summary

## First

budget-summary-needle first

## Second

budget-summary-needle second'
    local mode admission full_file bounded_file
    local -a mode_args admission_args
    for mode in text text-only; do
        mode_args=()
        [[ "$mode" != text-only ]] || mode_args+=(--text-only)
        for admission in unlimited result-limit per-file-limit; do
            admission_args=(--limit 0 --per-file 0)
            case "$admission" in
                result-limit) admission_args=(--limit 1 --per-file 0) ;;
                per-file-limit) admission_args=(--limit 0 --per-file 1) ;;
            esac
            full_file="$TEST_CONTENT_DIR/full-$mode-$admission.txt"
            bounded_file="$TEST_CONTENT_DIR/bounded-$mode-$admission.txt"
            "$SCRIPTS/search" "${mode_args[@]}" "${admission_args[@]}" \
                budget-summary-needle > "$full_file"
            if [[ "$admission" == unlimited ]]; then
                ! grep -q 'more result section(s)' "$full_file"
            else
                grep -q '1 more result section(s)' "$full_file"
            fi

            run bash -c '
                script="$1"; output="$2"; shift 2
                "$script" "$@" >"$output"
            ' _ "$SCRIPTS/search" "$bounded_file" "${mode_args[@]}" \
                "${admission_args[@]}" --max-bytes 10000 budget-summary-needle
            [[ "$status" -eq 0 ]]
            run cmp "$full_file" "$bounded_file"
            [[ "$status" -eq 0 ]]
        done
    done
}

@test "search text byte budgets accept an exact unbounded-response cap" {
    create_test_article "budget-exact.md" '# Budget Exact

## Evidence

budget-exact-needle'
    local mode full_file exact_file cap
    local -a mode_args
    for mode in text text-only; do
        mode_args=()
        [[ "$mode" != text-only ]] || mode_args+=(--text-only)
        full_file="$TEST_CONTENT_DIR/unbounded-$mode.txt"
        exact_file="$TEST_CONTENT_DIR/exact-unbounded-$mode.txt"
        "$SCRIPTS/search" "${mode_args[@]}" --limit 0 --per-file 0 \
            budget-exact-needle > "$full_file"
        cap="$(wc -c < "$full_file" | tr -d '[:space:]')"

        run bash -c '
            script="$1"; output="$2"; shift 2
            "$script" "$@" >"$output"
        ' _ "$SCRIPTS/search" "$exact_file" "${mode_args[@]}" \
            --limit 0 --per-file 0 --max-bytes "$cap" budget-exact-needle
        [[ "$status" -eq 0 ]]
        [[ "$(wc -c < "$exact_file" | tr -d '[:space:]')" -eq "$cap" ]]
        run cmp "$full_file" "$exact_file"
        [[ "$status" -eq 0 ]]
    done
}

@test "search output modes honor exact and one-byte-short budgets" {
    for i in 1 2 3; do
        create_test_article "matrix-$i.md" "# Matrix $i

## Evidence

matrix needle result $i with enough text for a complete output record."
    done

    for mode in json text text-only; do
        mode_args=()
        case "$mode" in
            json) mode_args+=(--json) ;;
            text-only) mode_args+=(--text-only) ;;
        esac
        full_file="$TEST_CONTENT_DIR/full-$mode"
        exact_file="$TEST_CONTENT_DIR/exact-$mode"
        short_file="$TEST_CONTENT_DIR/short-$mode"
        if [[ "$mode" == json ]]; then
            complete_file="$TEST_CONTENT_DIR/complete-$mode"
            "$SCRIPTS/search" "${mode_args[@]}" --limit 0 --per-file 0 \
                matrix needle >"$complete_file"
            expected_records="$(jq '.results | length' "$complete_file")"
            exact=10000
            for _ in 1 2 3 4 5 6 7 8 9 10; do
                "$SCRIPTS/search" "${mode_args[@]}" --limit 0 --per-file 0 \
                    --max-bytes "$exact" matrix needle >"$full_file"
                measured="$(wc -c < "$full_file" | tr -d '[:space:]')"
                [[ "$measured" -eq "$exact" ]] && break
                exact="$measured"
            done
            [[ "$measured" -eq "$exact" ]]
        else
            "$SCRIPTS/search" "${mode_args[@]}" --limit 0 --per-file 0 \
                --max-bytes 10000 matrix needle >"$full_file"
            exact="$(wc -c < "$full_file" | tr -d '[:space:]')"
        fi
        run bash -c '
            script="$1"; output="$2"; error="$3"; shift 3
            "$script" "$@" >"$output" 2>"$error"
        ' _ "$SCRIPTS/search" "$exact_file" "$TEST_CONTENT_DIR/exact.err" \
            "${mode_args[@]}" --limit 0 --per-file 0 --max-bytes "$exact" \
            matrix needle
        [[ "$status" -eq 0 ]]
        used="$(wc -c < "$exact_file" | tr -d '[:space:]')"
        [[ "$used" -le "$exact" ]]
        if [[ "$mode" == json ]]; then
            jq -e --argjson expected "$expected_records" --argjson cap "$exact" \
                '.max_bytes == $cap and .truncated == false and
                 .returned == $expected and .returned == .total_lines' \
                "$exact_file" >/dev/null
            [[ "$used" -eq "$exact" ]]
        else
            run cmp "$full_file" "$exact_file"
            [[ "$status" -eq 0 ]]
        fi

        short=$((exact - 1))
        run bash -c '
            script="$1"; output="$2"; error="$3"; shift 3
            "$script" "$@" >"$output" 2>"$error"
        ' _ "$SCRIPTS/search" "$short_file" "$TEST_CONTENT_DIR/short.err" \
            "${mode_args[@]}" --limit 0 --per-file 0 --max-bytes "$short" \
            matrix needle
        [[ "$status" -eq 0 ]]
        used="$(wc -c < "$short_file" | tr -d '[:space:]')"
        [[ "$used" -le "$short" ]]
        if [[ "$mode" == json ]]; then
            jq -e --argjson cap "$short" \
                --argjson expected "$expected_records" \
                '.max_bytes == $cap and .returned < $expected and
                 .returned < .total_lines and .truncated == true and
                 .omitted_results == (.total_lines - .returned)' \
                "$short_file" >/dev/null
            jq -n -e --slurpfile exact "$exact_file" --slurpfile short "$short_file" \
                '($short[0].results | length) as $short_count |
                 $short[0].results == $exact[0].results[:$short_count]'
        else
            grep -q 'output truncated' "$short_file"
        fi
    done
}

@test "search combines result, per-file, and byte limits" {
    for i in 1 2 3; do
        create_test_article "combined-limits-$i.md" "# Combined Limits $i

## First

combined-limits-needle $i first

## Second

combined-limits-needle $i second

## Third

combined-limits-needle $i third"
    done

    admitted_file="$TEST_CONTENT_DIR/admitted.json"
    "$SCRIPTS/search" --json --limit 5 --per-file 2 \
        combined-limits-needle >"$admitted_file"
    admitted_records="$(jq '.returned' "$admitted_file")"
    candidate_records="$(jq '.total_lines' "$admitted_file")"
    [[ "$admitted_records" -eq 5 ]]
    [[ "$candidate_records" -eq 9 ]]

    one_record_file="$TEST_CONTENT_DIR/one-record.json"
    "$SCRIPTS/search" --json --limit 1 --per-file 2 --max-bytes 10000 \
        combined-limits-needle >"$one_record_file"
    json_cap="$(wc -c < "$one_record_file" | tr -d '[:space:]')"
    json_file="$TEST_CONTENT_DIR/combined.json"
    json_error="$TEST_CONTENT_DIR/combined.err"
    run bash -c '"$1" --json --limit 5 --per-file 2 --max-bytes "$2" \
        --explain combined-limits-needle >"$3" 2>"$4"' \
        _ "$SCRIPTS/search" "$json_cap" "$json_file" "$json_error"
    [[ "$status" -eq 0 ]]
    json_bytes="$(wc -c < "$json_file" | tr -d '[:space:]')"
    [[ "$json_bytes" -le "$json_cap" ]]
    jq -e --argjson candidates "$candidate_records" --argjson admitted "$admitted_records" \
        '.total_lines == $candidates and .returned > 0 and
         .returned < $admitted and .truncated == true and
         .omitted_results == (.total_lines - .returned)' \
        "$json_file" >/dev/null
    jq -n -e --slurpfile admitted "$admitted_file" --slurpfile budget "$json_file" \
        '($budget[0].results | length) as $budget_count |
         $budget[0].results == $admitted[0].results[:$budget_count]' >/dev/null
    read -r json_result_omitted json_byte_omitted < <(
        sed -n 's/.*omissions: result\/per-file=\([0-9]*\); byte-budget=\([0-9]*\).*/\1 \2/p' \
            "$json_error"
    )
    [[ "$json_result_omitted" -gt 0 ]]
    [[ "$json_byte_omitted" -gt 0 ]]
    [[ $((json_result_omitted + json_byte_omitted)) -eq \
        $((candidate_records - $(jq '.returned' "$json_file"))) ]]
    grep -q "candidates: $candidate_records; returned:" "$json_error"

    text_one_record="$TEST_CONTENT_DIR/one-record.txt"
    "$SCRIPTS/search" --limit 1 --per-file 2 --max-bytes 10000 \
        combined-limits-needle >"$text_one_record"
    text_cap="$(wc -c < "$text_one_record" | tr -d '[:space:]')"
    text_file="$TEST_CONTENT_DIR/combined.txt"
    text_error="$TEST_CONTENT_DIR/combined.txt.err"
    run bash -c '"$1" --limit 5 --per-file 2 --max-bytes "$2" --explain \
        combined-limits-needle >"$3" 2>"$4"' \
        _ "$SCRIPTS/search" "$text_cap" "$text_file" "$text_error"
    [[ "$status" -eq 0 ]]
    text_bytes="$(wc -c < "$text_file" | tr -d '[:space:]')"
    [[ "$text_bytes" -le "$text_cap" ]]
    grep -q 'output truncated' "$text_file"
    read -r text_result_omitted text_byte_omitted < <(
        sed -n 's/.*omissions: result\/per-file=\([0-9]*\); byte-budget=\([0-9]*\).*/\1 \2/p' \
            "$text_error"
    )
    [[ "$text_result_omitted" -gt 0 ]]
    [[ "$text_byte_omitted" -gt 0 ]]
    text_returned="$(sed -n 's/.*candidates: [0-9]*; returned: \([0-9]*\);.*/\1/p' "$text_error")"
    [[ $((text_result_omitted + text_byte_omitted)) -eq \
        $((candidate_records - text_returned)) ]]
    grep -q "candidates: $candidate_records; returned: $text_returned" "$text_error"
}

@test "search rejects a byte budget smaller than the JSON envelope" {
    create_test_article "budget.md" '# Budget

needle'
    run "$SCRIPTS/search" --json --max-bytes 0 needle
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"minimum valid JSON response"* ]]
}

@test "search returns a valid empty JSON response for an empty scope intersection" {
    mkdir -p "$TEST_CONTENT_DIR/knowledge/one" "$TEST_CONTENT_DIR/knowledge/two"
    create_test_article "one/needle.md" '# One

needle'
    create_test_article "two/needle.md" '# Two

needle'
    run "$SCRIPTS/search" --json --max-bytes 400 --path knowledge/one --topic two needle
    [[ "$status" -eq 0 ]]
    run jq -e '.results == [] and .returned == 0 and .truncated == false' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "search text byte budgets signal omitted output" {
    create_test_article "budget.md" '# Budget

## Evidence

budget needle with a long enough result line to require truncation.'
    create_test_article "budget-two.md" '# Budget Two

## Evidence

budget needle with a long enough result line to require truncation.'
    run "$SCRIPTS/search" --text-only --max-bytes 200 needle
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"output truncated"* ]]
}

@test "search text byte budgets never skip a larger higher-ranked record" {
    long_dir="$(printf 'long%0.s' {1..35})"
    mkdir -p "$TEST_CONTENT_DIR/knowledge/$long_dir"
    create_test_article "$long_dir/high.md" '# High

## Needle

needle'
    create_test_article "low.md" '# Low

## Notes

needle'
    full_file="$TEST_CONTENT_DIR/search.txt"
    "$SCRIPTS/search" --limit 0 --per-file 0 needle >"$full_file"
    first_bytes="$(head -n 1 "$full_file" | wc -c | tr -d '[:space:]')"
    marker_bytes="$(printf '%s\n' '[output truncated: complete records omitted; increase --max-bytes]' | wc -c | tr -d '[:space:]')"
    cap=$((first_bytes + marker_bytes - 1))
    run "$SCRIPTS/search" --max-bytes "$cap" --limit 0 --per-file 0 needle
    [[ "$status" -ne 0 ]]
    [[ "$output" != *"low.md"* ]]
}

@test "question search preserves quoted command boundaries across lines" {
    create_test_article "multiline-command.md" $'# Command\n\n## Restart\nRun systemctl restart kb-api.'
    run "$SCRIPTS/search" --json --query $"What is 'systemctl
restart kb-api'?"
    [[ "$status" -eq 0 ]]
    jq -e '.query_terms == ["systemctl", "restart", "kb-api"] and .returned == 1' <<< "$output"
}

@test "search excludes standalone section metadata from evidence" {
    create_test_article "metadata-evidence.md" $'---\ntitle: Metadata evidence\nverified: 2026-10-04\n---\n# Metadata evidence\n\n## Service\n\n<!-- kb-section:\nstatus=current;\nsources=observations/archived/metadata-only-needle.md\n-->\nThe service listens on port 8080.'
    run "$SCRIPTS/search" --json metadata-only-needle
    [[ "$status" -eq 0 ]]
    jq -e '.returned == 0' <<< "$output"
    run "$SCRIPTS/search" --json 8080
    [[ "$status" -eq 0 ]]
    jq -e '.results[0].section_metadata.valid and .results[0].section_metadata.status == "current"' <<< "$output"
}

@test "search retains prose after an inline metadata comment closes" {
    local comment
    for comment in '<!-- kb-section: status=unresolved --> inline-evidence-needle' \
        $'<!-- kb-section:\nstatus=unresolved\n--> inline-evidence-needle'; do
        create_test_article "inline-closing.md" "---
title: Inline closing
verified: 2026-10-04
---
## Service
$comment
Body evidence."
        run "$SCRIPTS/search" --json inline-evidence-needle
        [[ "$status" -eq 0 ]]
        jq -e '.returned == 1 and
            .results[0].locator.number == "1" and
            .results[0].section_metadata.status == "current" and
            .results[0].conflict.status == "none" and
            (.results[0].text | contains("inline-evidence-needle"))' <<< "$output"
    done
}

@test "search serializes leading-zero TTLs as canonical JSON numbers" {
    create_test_article "decimal-ttl.md" $'---\ntitle: Decimal TTL\nverified: 2026-10-04\n---\n## Service\n<!-- kb-section: ttl=08 -->\nBody evidence.'
    local json_file="$TEST_CONTENT_DIR/ttl.json"
    local error_file="$TEST_CONTENT_DIR/ttl.stderr"
    run env FRESHNESS_TODAY_EPOCH=1792022400 bash -c '
        "$1" --json evidence > "$2" 2> "$3"
    ' _ "$SCRIPTS/search" "$json_file" "$error_file"
    [[ "$status" -eq 0 ]]
    # jq accepts 08, although JSON forbids leading zeroes in numeric literals.
    # Check the serialized field as well as its parsed value.
    run grep -E '"ttl_days":[[:space:]]*8[[:space:]]*[,}]' "$json_file"
    [[ "$status" -eq 0 ]]
    jq -e '.returned == 1 and .results[0].freshness.ttl_days == 8 and
        .results[0].freshness.status == "stale"' "$json_file"
    [[ ! -s "$error_file" ]]
}
