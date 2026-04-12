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

@test "context shows pending count" {
    create_test_observation "a.md" "Obs" "Body"
    run "$SCRIPTS/context"
    [[ "$output" == *"Pending observations: 1"* ]]
}
