#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

# --- status ---

@test "status runs with empty content" {
    run "$SCRIPTS/status"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Knowledge articles:    0"* ]]
    [[ "$output" == *"Pending observations:  0"* ]]
}

@test "status counts articles" {
    create_test_article "a.md" "# A"
    create_test_article "b.md" "# B"
    run "$SCRIPTS/status"
    [[ "$output" == *"Knowledge articles:    2"* ]]
}

@test "status shows content path" {
    run "$SCRIPTS/status"
    [[ "$output" == *"Content: $TEST_CONTENT_DIR"* ]]
}

@test "status --brief prints one line of live state" {
    create_test_article "a.md" '---
title: "A"
updated: 2026-08-08
verified: 2026-08-08
---

# A'
    create_test_observation "20260412T000000-aaaa.md" "Obs" "Body"
    create_test_question "20260412T000000-bbbb.md" "Who owns this?"

    run "$SCRIPTS/status" --brief
    [[ "$status" -eq 0 ]]
    [[ "${#lines[@]}" -eq 1 ]]
    [[ "$output" == *"1 articles"* ]]
    [[ "$output" == *"1 pending"* ]]
    [[ "$output" == *"1 open question(s)"* ]]
}

@test "status --brief counts stale articles" {
    create_test_article "old.md" '---
title: "Old"
updated: 2020-01-01
verified: 2020-01-01
---

# Old'
    run "$SCRIPTS/status" --brief
    [[ "$output" == *"1 stale"* ]]
}

@test "status rejects an unknown option" {
    run "$SCRIPTS/status" --bogus
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Unknown option"* ]]
}

# --- context ---

@test "context runs with empty content" {
    run "$SCRIPTS/context"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Topics: (none yet)"* ]]
    [[ "$output" == *"Pending observations: 0"* ]]
}

@test "context lists topics when articles exist" {
    create_test_article "networking.md" "# Networking

## DNS

Content."
    run "$SCRIPTS/context"
    [[ "$output" == *"Networking"* ]]
}

@test "context lists topics that live only in subdirectories" {
    create_test_article "infra/nas.md" "# NAS

## Bind mounts

Content."
    run "$SCRIPTS/context"
    [[ "$output" == *"Topics (1 files)"* ]]
    [[ "$output" == *"NAS"* ]]
    [[ "$output" != *"none yet"* ]]
}

@test "context counts sources in subdirectories" {
    mkdir -p "$TEST_CONTENT_DIR/sources/vendor"
    echo "# Doc" > "$TEST_CONTENT_DIR/sources/vendor/manual.md"
    run "$SCRIPTS/context"
    [[ "$output" == *"Source documents: 1"* ]]
}

@test "context shows pending count" {
    create_test_observation "a.md" "Obs" "Body"
    run "$SCRIPTS/context"
    [[ "$output" == *"Pending observations: 1"* ]]
}
