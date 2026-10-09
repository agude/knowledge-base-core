#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "observe creates file with correct frontmatter" {
    export KNOWLEDGE_OBSERVE=1
    run "$SCRIPTS/observe" --title "Test title" --body "Test body" --no-commit
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Wrote: observations/pending/"* ]]

    # Check the file exists and has correct content
    file=$(ls "$TEST_CONTENT_DIR/observations/pending/"*.md | head -1)
    [[ -f "$file" ]]
    grep -q 'title: "Test title"' "$file"
    grep -q 'source: session' "$file"
    grep -q 'Test body' "$file"
}

@test "observe respects custom --source" {
    export KNOWLEDGE_OBSERVE=1
    run "$SCRIPTS/observe" --title "Test" --body "Body" --source "slack" --no-commit
    [[ "$status" -eq 0 ]]
    file=$(ls "$TEST_CONTENT_DIR/observations/pending/"*.md | head -1)
    grep -q 'source: slack' "$file"
}

@test "observe works without KNOWLEDGE_OBSERVE set" {
    unset KNOWLEDGE_OBSERVE
    run "$SCRIPTS/observe" --title "Test" --body "Body" --no-commit
    [[ "$status" -eq 0 ]]
    count=$(ls "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l)
    [[ "$count" -eq 1 ]]
}

@test "observe requires --title" {
    export KNOWLEDGE_OBSERVE=1
    run "$SCRIPTS/observe" --body "Body" --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"--title is required"* ]]
}

@test "observe reads body from stdin with --body -" {
    echo "Piped body content" | KNOWLEDGE_OBSERVE=1 \
        "$SCRIPTS/observe" --title "Stdin test" --body - --no-commit
    file=$(ls "$TEST_CONTENT_DIR/observations/pending/"*.md | head -1)
    grep -q 'Piped body content' "$file"
}

@test "observe requires --body rather than silently reading stdin" {
    # Under an agent's Bash tool stdin is never a terminal, so the old
    # fallback turned a mistyped --body into an empty observation.
    run bash -c 'printf "" | KNOWLEDGE_OBSERVE=1 "$SCRIPTS/observe" --title "No body" --no-commit'
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"--body is required"* ]]
    count=$(ls "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l)
    [[ "$count" -eq 0 ]]
}

@test "observe filenames carry enough entropy to avoid collisions" {
    for i in 1 2 3 4 5; do
        KNOWLEDGE_OBSERVE=1 "$SCRIPTS/observe" --title "T$i" --body "B" --no-commit
    done
    # 8 hex digits after the timestamp
    for f in "$TEST_CONTENT_DIR/observations/pending/"*.md; do
        [[ "$(basename "$f")" =~ ^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}\.md$ ]]
    done
    count=$(ls "$TEST_CONTENT_DIR/observations/pending/"*.md | wc -l)
    [[ "$count" -eq 5 ]]
}

@test "observe escapes quotes in title" {
    export KNOWLEDGE_OBSERVE=1
    run "$SCRIPTS/observe" --title 'Say "hello"' --body "Body" --no-commit
    [[ "$status" -eq 0 ]]
    file=$(ls "$TEST_CONTENT_DIR/observations/pending/"*.md | head -1)
    grep -q 'Say \\"hello\\"' "$file"
}

# hold_lock - Take the commit lock on behalf of a live process.
hold_lock() {
    mkdir "$TEST_CONTENT_DIR/.observe.lock"
    echo $$ > "$TEST_CONTENT_DIR/.observe.lock/pid"
}

@test "observe leaves nothing in pending when the lock wait expires" {
    hold_lock
    run env KNOWLEDGE_LOCK_WAIT=0 "$SCRIPTS/observe" --title "Blocked" --body "Body"
    [[ "$status" -ne 0 ]]
    [[ -z "$(find "$TEST_CONTENT_DIR/observations/pending" -type f)" ]]
    # The lock belongs to a live process and must survive.
    [[ -f "$TEST_CONTENT_DIR/.observe.lock/pid" ]]
}

@test "observe waits up to KNOWLEDGE_LOCK_WAIT seconds" {
    hold_lock
    local start=$SECONDS
    run env KNOWLEDGE_LOCK_WAIT=1 "$SCRIPTS/observe" --title "Blocked" --body "Body"
    [[ "$status" -ne 0 ]]
    (( SECONDS - start < 3 ))
}

@test "observe rejects a non-numeric KNOWLEDGE_LOCK_WAIT" {
    run env KNOWLEDGE_LOCK_WAIT=soon "$SCRIPTS/observe" --title "T" --body "Body"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"KNOWLEDGE_LOCK_WAIT takes a non-negative number"* ]]
    [[ -z "$(find "$TEST_CONTENT_DIR/observations/pending" -type f)" ]]
}

# acquire_lock and release_lock replace the EXIT trap; the body buffer
# must still be removed after a committed observation.
@test "observe removes its temporary files and lock after committing" {
    local tmp="$BATS_TEST_TMPDIR/tmp"
    mkdir -p "$tmp"
    run env TMPDIR="$tmp" "$SCRIPTS/observe" --title "Clean" --body - <<< "Body"
    [[ "$status" -eq 0 ]]
    [[ -z "$(ls -A "$tmp")" ]]
    [[ ! -e "$TEST_CONTENT_DIR/.observe.lock" ]]
    [[ -z "$(find "$TEST_CONTENT_DIR/observations/pending" -name '.observation.*')" ]]
    run git -C "$TEST_CONTENT_DIR" log -1 --format=%s
    [[ "$output" == "Observe: Clean" ]]
}
