# test_helper.bash - Shared setup/teardown for bats tests.
#
# Creates a temporary content directory with the expected structure.
# Sets KB_CONTENT_DIR so scripts find it. Cleans up on teardown.

setup_content_dir() {
    export TEST_CONTENT_DIR="$(mktemp -d)"
    mkdir -p "$TEST_CONTENT_DIR"/{knowledge,observations/{pending,archived},questions/{open,resolved},sources}
    export KB_CONTENT_DIR="$TEST_CONTENT_DIR"
    export SCRIPTS="$BATS_TEST_DIRNAME/../scripts"

    # Init a git repo in content dir (needed for locked_commit, status)
    git -C "$TEST_CONTENT_DIR" init -q
    git -C "$TEST_CONTENT_DIR" config user.email "test@test.com"
    git -C "$TEST_CONTENT_DIR" config user.name "Test"
    # Need an initial commit for git log to work
    touch "$TEST_CONTENT_DIR/.gitkeep"
    git -C "$TEST_CONTENT_DIR" add .gitkeep
    git -C "$TEST_CONTENT_DIR" commit -q -m "init"
}

teardown_content_dir() {
    if [[ -n "${TEST_CONTENT_DIR:-}" ]] && [[ -d "$TEST_CONTENT_DIR" ]]; then
        rm -rf "$TEST_CONTENT_DIR"
    fi
}

# create_test_article - Write a markdown file into content/knowledge/.
#
# Usage: create_test_article "filename.md" "content"
create_test_article() {
    local name="$1"
    local content="$2"
    local dir
    dir="$(dirname "$name")"
    if [[ "$dir" != "." ]]; then
        mkdir -p "$TEST_CONTENT_DIR/knowledge/$dir"
    fi
    printf '%s\n' "$content" > "$TEST_CONTENT_DIR/knowledge/$name"
}

# create_test_observation - Write an observation into content/observations/pending/.
#
# Usage: create_test_observation "filename.md" "title" "body"
create_test_observation() {
    local name="$1"
    local title="$2"
    local body="$3"
    cat > "$TEST_CONTENT_DIR/observations/pending/$name" <<EOF
---
title: "$title"
source: session
created: 2026-04-12T00:00:00Z
---

$body
EOF
}

# create_test_question - Write a question into content/questions/open/.
#
# Usage: create_test_question "filename.md" "title" ["context"]
create_test_question() {
    local name="$1"
    local title="$2"
    local ctx="${3:-}"
    {
        echo "---"
        echo "title: \"$title\""
        echo "source: test"
        if [[ -n "$ctx" ]]; then
            echo "context: $ctx"
        fi
        echo "created: 2026-04-12T00:00:00Z"
        echo "---"
    } > "$TEST_CONTENT_DIR/questions/open/$name"
}
