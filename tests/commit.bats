#!/usr/bin/env bats

load test_helper

setup() {
    setup_content_dir
    mkdir -p "$TEST_CONTENT_DIR/.git/hooks"
    ln -sfn "$SCRIPTS/hooks/pre-commit" "$TEST_CONTENT_DIR/.git/hooks/pre-commit"
}
teardown() { teardown_content_dir; }

article() {
    cat > "$TEST_CONTENT_DIR/knowledge/$1" <<EOF
---
title: "$2"
updated: 2020-01-01
verified: 2026-08-08
---

# $2

## Section

Content.
EOF
}

@test "commit requires a message" {
    run "$SCRIPTS/commit"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"-m is required"* ]]
}

@test "commit reports nothing to do on a clean tree" {
    run "$SCRIPTS/commit" -m "Curate: nothing"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Nothing to commit"* ]]
}

@test "commit stages and commits articles" {
    article "net.md" "Networking"
    run "$SCRIPTS/commit" -m "Curate: networking"
    [[ "$status" -eq 0 ]]
    run git -C "$TEST_CONTENT_DIR" log -1 --format=%s
    [[ "$output" == "Curate: networking" ]]
}

@test "commit keeps the hook's updated stamp" {
    article "net.md" "Networking"
    "$SCRIPTS/commit" -m "Curate: networking"
    committed="$(git -C "$TEST_CONTENT_DIR" show HEAD:knowledge/net.md)"
    [[ "$committed" == *"updated: $(date -u +%Y-%m-%d)"* ]]
    [[ "$committed" != *"updated: 2020-01-01"* ]]
}

@test "commit fails when an article does not lint" {
    cat > "$TEST_CONTENT_DIR/knowledge/bad.md" <<'EOF'
---
title: "Bad"
updated: 2026-08-08
verified: 2026-08-08
---

# One

## S

Content.

# Two

## T

Content.
EOF
    run "$SCRIPTS/commit" -m "Curate: bad"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"second H1"* ]]
}

@test "commit releases the lock when the hook rejects" {
    cat > "$TEST_CONTENT_DIR/knowledge/bad.md" <<'EOF'
---
title: "Bad"
updated: 2026-08-08
verified: 2026-08-08
---

# One

## S

Content.

# Two
EOF
    run "$SCRIPTS/commit" -m "Curate: bad"
    [[ ! -d "$TEST_CONTENT_DIR/.observe.lock" ]]
}

@test "commit picks up archived observations" {
    create_test_observation "20260412T000000-aaaa.md" "Obs" "Body"
    git -C "$TEST_CONTENT_DIR" add observations/
    git -C "$TEST_CONTENT_DIR" commit -q -m "Observe: Obs"

    mv "$TEST_CONTENT_DIR/observations/pending/20260412T000000-aaaa.md" \
       "$TEST_CONTENT_DIR/observations/archived/"
    run "$SCRIPTS/commit" -m "Curate: archive"
    [[ "$status" -eq 0 ]]
    # git records this as a rename; what matters is that the move landed.
    run git -C "$TEST_CONTENT_DIR" ls-tree -r --name-only HEAD
    [[ "$output" == *"observations/archived/20260412T000000-aaaa.md"* ]]
    [[ "$output" != *"observations/pending/20260412T000000-aaaa.md"* ]]
}
