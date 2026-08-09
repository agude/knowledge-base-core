#!/usr/bin/env bats
#
# The content-repo pre-commit hook: stamp `updated:` on staged articles,
# reject the commit on lint errors, and stay out of the way otherwise.

load test_helper

setup() {
    setup_content_dir
    mkdir -p "$TEST_CONTENT_DIR/.git/hooks"
    ln -sfn "$SCRIPTS/hooks/pre-commit" "$TEST_CONTENT_DIR/.git/hooks/pre-commit"
    TODAY="$(date -u +%Y-%m-%d)"
}
teardown() { teardown_content_dir; }

good_article() {
    cat <<EOF
---
title: "Networking"
updated: 2020-01-01
verified: 2026-08-08
---

# Networking

## DNS

$1
EOF
}

@test "pre-commit stamps updated on a staged article" {
    good_article "How DNS works." > "$TEST_CONTENT_DIR/knowledge/net.md"
    git -C "$TEST_CONTENT_DIR" add knowledge/net.md
    run git -C "$TEST_CONTENT_DIR" commit -q -m "Add networking"
    [[ "$status" -eq 0 ]]

    committed="$(git -C "$TEST_CONTENT_DIR" show HEAD:knowledge/net.md)"
    [[ "$committed" == *"updated: $TODAY"* ]]
    [[ "$committed" != *"updated: 2020-01-01"* ]]
}

@test "pre-commit leaves verified alone" {
    good_article "How DNS works." > "$TEST_CONTENT_DIR/knowledge/net.md"
    git -C "$TEST_CONTENT_DIR" add knowledge/net.md
    git -C "$TEST_CONTENT_DIR" commit -q -m "Add networking"

    committed="$(git -C "$TEST_CONTENT_DIR" show HEAD:knowledge/net.md)"
    [[ "$committed" == *"verified: 2026-08-08"* ]]
}

@test "pre-commit rejects a lint error" {
    cat > "$TEST_CONTENT_DIR/knowledge/bad.md" <<'EOF'
---
title: "Bad"
updated: 2026-08-08
verified: 2026-08-08
---

# One

## Section

Content.

# Two

## Other

Content.
EOF
    git -C "$TEST_CONTENT_DIR" add knowledge/bad.md
    run git -C "$TEST_CONTENT_DIR" commit -q -m "Add bad article"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"second H1"* ]]
    [[ "$output" == *"commit rejected"* ]]
}

@test "pre-commit lets an oversized section through as a warning" {
    {
        echo "---"
        echo "title: \"Long\""
        echo "updated: 2026-08-08"
        echo "verified: 2026-08-08"
        echo "---"
        echo ""
        echo "# Long"
        echo ""
        echo "## Big"
        echo ""
        printf 'filler\n%.0s' $(seq 60)
    } > "$TEST_CONTENT_DIR/knowledge/long.md"
    git -C "$TEST_CONTENT_DIR" add knowledge/long.md
    run git -C "$TEST_CONTENT_DIR" commit -q -m "Add long article"
    [[ "$status" -eq 0 ]]
}

@test "pre-commit ignores commits with no staged articles" {
    create_test_observation "20260412T000000-aaaa.md" "Obs" "Body"
    git -C "$TEST_CONTENT_DIR" add observations/pending/20260412T000000-aaaa.md
    run git -C "$TEST_CONTENT_DIR" commit -q -m "Observe: Obs"
    [[ "$status" -eq 0 ]]
    [[ "$output" != *"stamped"* ]]
}

@test "observe still commits with the hook installed" {
    run "$SCRIPTS/observe" --title "Test" --body "Body"
    [[ "$status" -eq 0 ]]
    run git -C "$TEST_CONTENT_DIR" log -1 --format=%s
    [[ "$output" == "Observe: Test" ]]
}

@test "pre-commit does not restamp an article already dated today" {
    good_article "First." > "$TEST_CONTENT_DIR/knowledge/net.md"
    git -C "$TEST_CONTENT_DIR" add knowledge/net.md
    git -C "$TEST_CONTENT_DIR" commit -q -m "Add"

    printf 'Second edit.\n' >> "$TEST_CONTENT_DIR/knowledge/net.md"
    git -C "$TEST_CONTENT_DIR" add knowledge/net.md
    run git -C "$TEST_CONTENT_DIR" commit -q -m "Edit"
    [[ "$status" -eq 0 ]]
    [[ "$output" != *"stamped"* ]]
}

@test "pre-commit skips stamping on a partial commit instead of losing it" {
    good_article "How DNS works." > "$TEST_CONTENT_DIR/knowledge/net.md"
    git -C "$TEST_CONTENT_DIR" add knowledge/net.md
    run git -C "$TEST_CONTENT_DIR" commit -q -m "Add" -- knowledge/net.md
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"partial commit"* ]]

    committed="$(git -C "$TEST_CONTENT_DIR" show HEAD:knowledge/net.md)"
    [[ "$committed" == *"updated: 2020-01-01"* ]]
}
