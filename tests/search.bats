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

@test "search shows 'top' when match is before any H2" {
    create_test_article "topic.md" "---
title: \"Matched in frontmatter\"
---

# Topic

Preamble with target_word here."
    run "$SCRIPTS/search" "target_word"
    [[ "$output" == *"| top |"* ]]
}
