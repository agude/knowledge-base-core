#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "pending shows 0 when empty" {
    run "$SCRIPTS/pending" --count
    [[ "$output" == "0" ]]
}

@test "pending --count returns correct number" {
    create_test_observation "a.md" "First" "Body one"
    create_test_observation "b.md" "Second" "Body two"
    run "$SCRIPTS/pending" --count
    [[ "$output" == "2" ]]
}

@test "pending lists titles" {
    create_test_observation "a.md" "First observation" "Body"
    run "$SCRIPTS/pending"
    [[ "$output" == *"First observation"* ]]
    [[ "$output" == *"1 pending"* ]]
}

@test "pending --full shows file content" {
    create_test_observation "a.md" "Test" "Full body text here"
    run "$SCRIPTS/pending" --full
    [[ "$output" == *"Full body text here"* ]]
}
