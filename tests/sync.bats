#!/usr/bin/env bats

load test_helper

setup() {
    setup_content_dir
    REMOTE="$(mktemp -d)"
    git init -q --bare "$REMOTE"
    git -C "$TEST_CONTENT_DIR" remote add origin "$REMOTE"
    git -C "$TEST_CONTENT_DIR" push -q -u origin main 2>/dev/null \
        || git -C "$TEST_CONTENT_DIR" push -q -u origin master
    BRANCH="$(git -C "$TEST_CONTENT_DIR" rev-parse --abbrev-ref HEAD)"
}

teardown() {
    teardown_content_dir
    [[ -n "${REMOTE:-}" ]] && rm -rf "$REMOTE"
}

# clone_and_commit - A second machine committing its own observation.
clone_and_commit() {
    OTHER="$(mktemp -d)"
    git clone -q "$REMOTE" "$OTHER"
    git -C "$OTHER" config user.email "other@test.com"
    git -C "$OTHER" config user.name "Other"
    mkdir -p "$OTHER/observations/pending"
    echo "from another machine" > "$OTHER/observations/pending/20260101T000000-ffff.md"
    git -C "$OTHER" add -A
    git -C "$OTHER" commit -q -m "Observe: from another machine"
    git -C "$OTHER" push -q origin HEAD
    rm -rf "$OTHER"
}

@test "sync reports being in sync" {
    run "$SCRIPTS/sync"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Already in sync"* ]]
}

@test "sync --status reports counts without changing anything" {
    clone_and_commit
    run "$SCRIPTS/sync" --status
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"0 to push, 1 to pull"* ]]
    [[ ! -f "$TEST_CONTENT_DIR/observations/pending/20260101T000000-ffff.md" ]]
}

@test "sync pulls another machine's observations" {
    clone_and_commit
    run "$SCRIPTS/sync"
    [[ "$status" -eq 0 ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/20260101T000000-ffff.md" ]]
}

@test "sync pushes local observations" {
    KNOWLEDGE_OBSERVE=1 "$SCRIPTS/observe" --title "Local" --body "Body"
    run "$SCRIPTS/sync"
    [[ "$status" -eq 0 ]]
    run git -C "$REMOTE" log -1 --format=%s
    [[ "$output" == "Observe: Local" ]]
}

@test "sync rebases local commits on top of remote ones" {
    KNOWLEDGE_OBSERVE=1 "$SCRIPTS/observe" --title "Local" --body "Body"
    clone_and_commit
    run "$SCRIPTS/sync"
    [[ "$status" -eq 0 ]]
    run git -C "$TEST_CONTENT_DIR" log --format=%s -2
    [[ "$output" == *"Observe: Local"* ]]
    [[ "$output" == *"Observe: from another machine"* ]]
    # Rebase, not merge
    run git -C "$TEST_CONTENT_DIR" log --merges --format=%s
    [[ -z "$output" ]]
}

@test "sync refuses to run with uncommitted changes" {
    echo "half-written" > "$TEST_CONTENT_DIR/knowledge/wip.md"
    run "$SCRIPTS/sync"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Uncommitted changes"* ]]
}

@test "sync fails cleanly with no remote" {
    git -C "$TEST_CONTENT_DIR" remote remove origin
    run "$SCRIPTS/sync"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"No 'origin' remote"* ]]
}

@test "sync --no-push pulls only" {
    KNOWLEDGE_OBSERVE=1 "$SCRIPTS/observe" --title "Local" --body "Body"
    clone_and_commit
    run "$SCRIPTS/sync" --no-push
    [[ "$status" -eq 0 ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/20260101T000000-ffff.md" ]]
    run git -C "$REMOTE" log -1 --format=%s
    [[ "$output" == "Observe: from another machine" ]]
}

@test "sync releases the lock" {
    clone_and_commit
    run "$SCRIPTS/sync"
    [[ ! -d "$TEST_CONTENT_DIR/.observe.lock" ]]
}

@test "sync rejects an unknown option" {
    run "$SCRIPTS/sync" --bogus
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Unknown option"* ]]
}
