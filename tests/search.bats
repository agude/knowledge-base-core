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
