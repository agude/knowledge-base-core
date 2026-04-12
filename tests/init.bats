#!/usr/bin/env bats

@test "init creates all content directories" {
    TARGET="$(mktemp -d)"
    rm -rf "$TARGET"

    run "$BATS_TEST_DIRNAME/../scripts/init" --path "$TARGET"
    [[ "$status" -eq 0 ]]
    [[ -d "$TARGET/knowledge" ]]
    [[ -d "$TARGET/observations/pending" ]]
    [[ -d "$TARGET/observations/archived" ]]
    [[ -d "$TARGET/questions/open" ]]
    [[ -d "$TARGET/questions/resolved" ]]
    [[ -d "$TARGET/sources" ]]

    rm -rf "$TARGET"
}

@test "init initializes a git repo" {
    TARGET="$(mktemp -d)"
    rm -rf "$TARGET"

    run "$BATS_TEST_DIRNAME/../scripts/init" --path "$TARGET"
    [[ -d "$TARGET/.git" ]]
    # Should have an initial commit
    count="$(git -C "$TARGET" rev-list --count HEAD)"
    [[ "$count" -eq 1 ]]

    rm -rf "$TARGET"
}

@test "init creates .gitkeep files" {
    TARGET="$(mktemp -d)"
    rm -rf "$TARGET"

    run "$BATS_TEST_DIRNAME/../scripts/init" --path "$TARGET"
    [[ -f "$TARGET/knowledge/.gitkeep" ]]
    [[ -f "$TARGET/observations/pending/.gitkeep" ]]
    [[ -f "$TARGET/sources/.gitkeep" ]]

    rm -rf "$TARGET"
}

@test "init is safe to run twice" {
    TARGET="$(mktemp -d)"
    rm -rf "$TARGET"

    "$BATS_TEST_DIRNAME/../scripts/init" --path "$TARGET"
    run "$BATS_TEST_DIRNAME/../scripts/init" --path "$TARGET"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"exists:"* ]]
    [[ "$output" == *"already initialized"* ]]

    rm -rf "$TARGET"
}

@test "init uses CONTENT_DIR when no --path given" {
    export KB_CONTENT_DIR="$(mktemp -d)"
    rm -rf "$KB_CONTENT_DIR"

    run "$BATS_TEST_DIRNAME/../scripts/init"
    [[ "$status" -eq 0 ]]
    [[ -d "$KB_CONTENT_DIR/knowledge" ]]
    [[ -d "$KB_CONTENT_DIR/.git" ]]

    rm -rf "$KB_CONTENT_DIR"
}
