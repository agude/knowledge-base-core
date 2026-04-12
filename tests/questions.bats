#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "questions shows 'no open questions' when empty" {
    run "$SCRIPTS/questions"
    [[ "$output" == *"No open questions"* ]]
}

@test "questions lists open questions" {
    create_test_question "q1.md" "Who owns deploys?"
    run "$SCRIPTS/questions"
    [[ "$output" == *"Who owns deploys?"* ]]
}

@test "questions --path filters by context" {
    create_test_question "q1.md" "Deploy question" "knowledge/deploys/canary.md"
    create_test_question "q2.md" "Unrelated question"
    run "$SCRIPTS/questions" --path knowledge/deploys
    [[ "$output" == *"Deploy question"* ]]
    [[ "$output" != *"Unrelated question"* ]]
}

@test "questions --file reads single question" {
    create_test_question "q1.md" "Test question"
    run "$SCRIPTS/questions" --file q1.md
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Test question"* ]]
}

# --- ask ---

@test "ask creates question file" {
    run "$SCRIPTS/ask" --title "New question?" --no-commit
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Wrote: questions/open/"* ]]
    file=$(ls "$TEST_CONTENT_DIR/questions/open/"*.md | head -1)
    grep -q 'New question?' "$file"
}

@test "ask includes --context in frontmatter" {
    create_test_article "topic.md" "# Topic"
    run "$SCRIPTS/ask" --title "About topic?" --context knowledge/topic.md --no-commit
    [[ "$status" -eq 0 ]]
    file=$(ls "$TEST_CONTENT_DIR/questions/open/"*.md | head -1)
    grep -q 'context: knowledge/topic.md' "$file"
}

@test "ask includes --body" {
    run "$SCRIPTS/ask" --title "Question?" --body "Extra context here" --no-commit
    file=$(ls "$TEST_CONTENT_DIR/questions/open/"*.md | head -1)
    grep -q 'Extra context here' "$file"
}

# --- resolve ---

@test "resolve moves question to resolved" {
    create_test_question "q1.md" "Test question"
    run "$SCRIPTS/resolve" --file q1.md --answer "Answered." --no-commit
    [[ "$status" -eq 0 ]]
    [[ ! -f "$TEST_CONTENT_DIR/questions/open/q1.md" ]]
    [[ -f "$TEST_CONTENT_DIR/questions/resolved/q1.md" ]]
    grep -q "Answered." "$TEST_CONTENT_DIR/questions/resolved/q1.md"
}

@test "resolve appends resolution section" {
    create_test_question "q1.md" "Test question"
    run "$SCRIPTS/resolve" --file q1.md --answer "See docs." --no-commit
    grep -q "## Resolution" "$TEST_CONTENT_DIR/questions/resolved/q1.md"
}

@test "resolve fails for nonexistent question" {
    run "$SCRIPTS/resolve" --file nonexistent.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Not found"* ]]
}
