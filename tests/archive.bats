#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "archive moves file from pending to archived" {
    create_test_observation "obs1.md" "Test" "Body"
    git -C "$TEST_CONTENT_DIR" add observations/pending/obs1.md
    git -C "$TEST_CONTENT_DIR" commit -q -m "add obs"

    run "$SCRIPTS/archive" obs1.md --no-commit
    [[ "$status" -eq 0 ]]
    [[ ! -f "$TEST_CONTENT_DIR/observations/pending/obs1.md" ]]
    [[ -f "$TEST_CONTENT_DIR/observations/archived/obs1.md" ]]
    [[ "$output" == *"Archived: observations/pending/obs1.md"* ]]
}

@test "archive handles multiple files" {
    create_test_observation "a.md" "First" "Body"
    create_test_observation "b.md" "Second" "Body"
    git -C "$TEST_CONTENT_DIR" add observations/
    git -C "$TEST_CONTENT_DIR" commit -q -m "add obs"

    run "$SCRIPTS/archive" a.md b.md --no-commit
    [[ "$status" -eq 0 ]]
    [[ ! -f "$TEST_CONTENT_DIR/observations/pending/a.md" ]]
    [[ ! -f "$TEST_CONTENT_DIR/observations/pending/b.md" ]]
    [[ -f "$TEST_CONTENT_DIR/observations/archived/a.md" ]]
    [[ -f "$TEST_CONTENT_DIR/observations/archived/b.md" ]]
}

@test "archive --all moves everything" {
    create_test_observation "a.md" "First" "Body"
    create_test_observation "b.md" "Second" "Body"
    create_test_observation "c.md" "Third" "Body"
    git -C "$TEST_CONTENT_DIR" add observations/
    git -C "$TEST_CONTENT_DIR" commit -q -m "add obs"

    run "$SCRIPTS/archive" --all --no-commit
    [[ "$status" -eq 0 ]]
    # pending should be empty (except .gitkeep)
    count=$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l | tr -d ' ')
    [[ "$count" -eq 0 ]]
    # archived should have all three
    count=$(find "$TEST_CONTENT_DIR/observations/archived" -name '*.md' -type f | wc -l | tr -d ' ')
    [[ "$count" -eq 3 ]]
}

@test "archive fails for nonexistent file" {
    run "$SCRIPTS/archive" nonexistent.md --no-commit
    [[ "$output" == *"Not found"* ]]
}

@test "archive with no args prints message" {
    run "$SCRIPTS/archive" --no-commit
    [[ "$output" == *"No files to archive"* ]]
}

@test "archive preserves file content" {
    create_test_observation "obs1.md" "Important" "Critical body content"
    git -C "$TEST_CONTENT_DIR" add observations/
    git -C "$TEST_CONTENT_DIR" commit -q -m "add obs"

    "$SCRIPTS/archive" obs1.md --no-commit
    grep -q "Critical body content" "$TEST_CONTENT_DIR/observations/archived/obs1.md"
    grep -q "Important" "$TEST_CONTENT_DIR/observations/archived/obs1.md"
}
