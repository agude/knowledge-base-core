#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

# --- need_arg ---

@test "need_arg fails when no argument follows flag" {
    source "$SCRIPTS/_lib.sh"
    run need_arg "--title" 1
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"requires an argument"* ]]
}

@test "need_arg succeeds when argument follows flag" {
    source "$SCRIPTS/_lib.sh"
    run need_arg "--title" 2
    [[ "$status" -eq 0 ]]
}

# --- yaml_escape ---

@test "yaml_escape escapes double quotes" {
    source "$SCRIPTS/_lib.sh"
    result="$(yaml_escape 'say "hello"')"
    [[ "$result" == 'say \"hello\"' ]]
}

@test "yaml_escape escapes backslashes" {
    source "$SCRIPTS/_lib.sh"
    result="$(yaml_escape 'path\to\file')"
    [[ "$result" == 'path\\to\\file' ]]
}

# --- frontmatter_field ---

@test "frontmatter_field extracts unquoted value" {
    create_test_article "fm-test.md" "---
source: session
---"
    source "$SCRIPTS/_lib.sh"
    result="$(frontmatter_field "source" "$TEST_CONTENT_DIR/knowledge/fm-test.md")"
    [[ "$result" == "session" ]]
}

@test "frontmatter_field extracts quoted value" {
    create_test_article "fm-test.md" '---
title: "Hello World"
---'
    source "$SCRIPTS/_lib.sh"
    result="$(frontmatter_field "title" "$TEST_CONTENT_DIR/knowledge/fm-test.md")"
    [[ "$result" == "Hello World" ]]
}

@test "frontmatter_field returns 1 for missing field" {
    create_test_article "fm-test.md" "---
title: test
---"
    source "$SCRIPTS/_lib.sh"
    run frontmatter_field "missing" "$TEST_CONTENT_DIR/knowledge/fm-test.md"
    [[ "$status" -ne 0 ]]
}

# --- resolve_path ---

@test "resolve_path finds knowledge-relative path" {
    create_test_article "topic.md" "# Topic"
    source "$SCRIPTS/_lib.sh"
    result="$(resolve_path "knowledge/topic.md")"
    [[ "$result" == "knowledge/topic.md" ]]
}

@test "resolve_path prepends knowledge/ for bare filename" {
    create_test_article "topic.md" "# Topic"
    source "$SCRIPTS/_lib.sh"
    result="$(resolve_path "topic.md")"
    [[ "$result" == "knowledge/topic.md" ]]
}

@test "resolve_path fails for nonexistent file" {
    source "$SCRIPTS/_lib.sh"
    run resolve_path "no-such-file.md"
    [[ "$status" -ne 0 ]]
}
