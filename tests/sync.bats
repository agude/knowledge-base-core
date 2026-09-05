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
    if [[ -n "${SYNC_TEST_TMP:-}" ]]; then
        rm -rf "$SYNC_TEST_TMP"
    fi
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

content_git() {
    ( cd "$TEST_CONTENT_DIR" && git "$@" )
}

other_git() {
    ( cd "$OTHER" && git "$@" )
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

@test "sync reports fetch failure instead of using cached state" {
    content_git remote set-url origin "$REMOTE/unavailable"
    run "$SCRIPTS/sync"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"remote state could not be verified"* ]]
    [[ "$output" != *"Already in sync"* ]]
}

@test "sync --status reports fetch failure instead of using cached state" {
    content_git remote set-url origin "$REMOTE/unavailable"
    run "$SCRIPTS/sync" --status
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"remote state could not be verified"* ]]
    [[ "$output" != *"In sync"* ]]
}

@test "sync rejects unavailable remote tracking information" {
    content_git config --unset-all remote.origin.fetch
    content_git update-ref -d "refs/remotes/origin/$BRANCH"
    run "$SCRIPTS/sync" --status
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"remote state could not be verified"* ]]
    [[ "$output" != *"In sync"* ]]
}

@test "sync rechecks for observations written during fetch" {
    SYNC_TEST_TMP="$(mktemp -d)"
    REAL_GIT="$(command -v git)"
    export REAL_GIT
    export SYNC_FETCH_STARTED="$SYNC_TEST_TMP/fetch-started"
    export SYNC_FETCH_RELEASE="$SYNC_TEST_TMP/fetch-release"
    cat > "$SYNC_TEST_TMP/git" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == fetch ]]; then
    : > "$SYNC_FETCH_STARTED"
    attempt=0
    while [[ ! -f "$SYNC_FETCH_RELEASE" && "$attempt" -lt 100 ]]; do
        attempt=$((attempt + 1))
        sleep 0.05
    done
fi
exec "$REAL_GIT" "$@"
EOF
    chmod +x "$SYNC_TEST_TMP/git"

    PATH="$SYNC_TEST_TMP:$PATH" "$SCRIPTS/sync" \
        > "$SYNC_TEST_TMP/output" 2>&1 &
    sync_pid=$!
    attempt=0
    while [[ ! -f "$SYNC_FETCH_STARTED" && "$attempt" -lt 100 ]]; do
        attempt=$((attempt + 1))
        sleep 0.05
    done
    [[ -f "$SYNC_FETCH_STARTED" ]]

    KNOWLEDGE_OBSERVE=1 "$SCRIPTS/observe" \
        --title "Concurrent" --body "Written during sync" \
        > "$SYNC_TEST_TMP/observer-output" 2>&1 &
    observer_pid=$!
    pending_path=""
    attempt=0
    while [[ -z "$pending_path" && "$attempt" -lt 100 ]]; do
        pending_path="$(find "$TEST_CONTENT_DIR/observations/pending" \
            -name '*.md' -type f -print -quit)"
        attempt=$((attempt + 1))
        sleep 0.05
    done
    [[ -n "$pending_path" ]]
    touch "$SYNC_FETCH_RELEASE"

    sync_status=0
    wait "$sync_pid" || sync_status=$?
    [[ "$sync_status" -ne 0 ]]
    observer_status=0
    wait "$observer_pid" || observer_status=$?
    [[ "$observer_status" -eq 0 ]]
    output="$(<"$SYNC_TEST_TMP/output")"
    [[ "$output" == *"Uncommitted changes"* ]]
}

@test "sync leaves rebase conflicts for resolution" {
    printf 'base\n' > "$TEST_CONTENT_DIR/knowledge/conflict.md"
    content_git add knowledge/conflict.md
    content_git commit -qm "Add conflict fixture"
    content_git push -q origin "$BRANCH"

    printf 'local\n' > "$TEST_CONTENT_DIR/knowledge/conflict.md"
    content_git commit -qam "Local conflict"

    OTHER="$(mktemp -d)"
    git clone -q "$REMOTE" "$OTHER"
    other_git config user.email "other@test.com"
    other_git config user.name "Other"
    printf 'remote\n' > "$OTHER/knowledge/conflict.md"
    other_git commit -qam "Remote conflict"
    other_git push -q origin HEAD
    rm -rf "$OTHER"

    run "$SCRIPTS/sync"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Rebase failed"* ]]
    [[ -d "$TEST_CONTENT_DIR/.git/rebase-merge" || \
        -d "$TEST_CONTENT_DIR/.git/rebase-apply" ]]
    [[ ! -d "$TEST_CONTENT_DIR/.observe.lock" ]]
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
