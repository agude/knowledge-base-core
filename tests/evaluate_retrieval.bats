#!/usr/bin/env bats

load test_helper

FIXTURE="$BATS_TEST_DIRNAME/fixtures/retrieval-v1/retrieval-v1.json"
FIXTURE_CONTENT="$BATS_TEST_DIRNAME/fixtures/retrieval-v1/content"

setup() {
    setup_content_dir
    cp -R "$FIXTURE_CONTENT/knowledge/." "$TEST_CONTENT_DIR/knowledge/"
}

teardown() { teardown_content_dir; }

@test "public retrieval fixture has versioned coverage cases" {
    run jq -e '
        .format == "knowledge-base-retrieval-evaluation" and
        .version == 1 and
        (.cases | length >= 30 and length <= 50) and
        ([.cases[].category] | index("exact_command_or_name")) != null and
        ([.cases[].category] | index("paraphrase")) != null and
        ([.cases[].category] | index("cross_article")) != null and
        ([.cases[].category] | index("changed_fact")) != null and
        ([.cases[].category] | index("conflicting_evidence")) != null and
        ([.cases[].category] | index("absent_answer")) != null
    ' "$FIXTURE"
    [[ "$status" -eq 0 ]]

    run jq -e '
        .format == "knowledge-base-retrieval-evaluation-baseline" and
        .version == 1 and
        (.cases | length == 36)
    ' "$BATS_TEST_DIRNAME/fixtures/retrieval-v1/retrieval-v1.baseline.json"
    [[ "$status" -eq 0 ]]
}

@test "evaluation reports per-case metrics and aggregate evidence scores" {
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$FIXTURE" --content-dir "$TEST_CONTENT_DIR" \
        --baseline "$BATS_TEST_DIRNAME/fixtures/retrieval-v1/retrieval-v1.baseline.json" \
        --json
    [[ "$status" -eq 0 ]]
    report="$output"

    run jq -e '
        .format == "knowledge-base-retrieval-evaluation-report" and
        .version == 1 and
        .measurement.top_k == 5 and
        .measurement.coverage_unit == "distinct {path, section} locators from the full ranking" and
        .measurement.full_ranking_command == "search --json --limit 0 --per-file 0 QUERY" and
        .measurement.top_five_command == "search --json --limit 5 --per-file 0 QUERY" and
        .summary.total_cases == 36 and
        .summary.answerable_cases == 31 and
        .summary.unanswerable_cases == 5 and
        .summary.passed_cases == 18 and
        .summary.failed_cases == 13 and
        .summary.any_required_evidence_cases == 18 and
        .summary.all_required_evidence_cases == 18 and
        (.cases | length == 36) and
        (all(.cases[];
            (.id | type) == "string" and
            (.full_ranking_response_bytes | type) == "number" and
            .full_ranking_response_bytes >= 0 and
            (.full_ranking_latency_ms | type) == "number" and
            .full_ranking_latency_ms >= 0 and
            (.top_five_response_bytes | type) == "number" and
            .top_five_response_bytes >= 0 and
            (.top_five_latency_ms | type) == "number" and
            .top_five_latency_ms >= 0 and
            (.top_five | length <= 5) and
            (.top_five | length == (unique | length)) and
            (.bounded_raw_results | type) == "array"
        )) and
        (all(.cases[] | select(.unanswerable == false);
            (.any_required_evidence | type) == "boolean" and
            (.all_required_evidence | type) == "boolean"
        )) and
        (all(.cases[] | select(.unanswerable == true);
            .status == "unanswerable" and
            .any_required_evidence == null and
            .all_required_evidence == null
        )) and
        (.failures | length) == .summary.failed_cases and
        (all(.cases[]; .full_ranking_response_bytes >= .top_five_response_bytes)) and
        (any(.cases[]; .full_ranking_response_bytes == .top_five_response_bytes)) and
        ([(.cases[] | select(
            .id == "cross-article-03" or
            .id == "cross-article-04" or
            .id == "conflict-01" or
            .id == "conflict-02"
        ))] | length == 4 and
            all(.[]; .top_five_raw_result_count == .top_five_section_count))
    ' <<< "$report"
    [[ "$status" -eq 0 ]]
    run jq -e '
        .baseline_comparison.fixture_match and
        .baseline_comparison.corpus_match and
        (.baseline_comparison.changed_cases | length > 0) and
        (.baseline_comparison.regressions | length == 0) and
        (all(.cases[] | select(.id | startswith("exact-command-")); .status == "pass" and .first_relevant_rank == 1))
    ' <<< "$report"
    [[ "$status" -eq 0 ]]
}

@test "evaluation can select content independently of KB_CONTENT_DIR" {
    run env -u KB_CONTENT_DIR "$SCRIPTS/evaluate-retrieval" \
        --fixture "$FIXTURE" --content-dir "$TEST_CONTENT_DIR" --json
    [[ "$status" -eq 0 ]]
    run jq -e '.corpus_id == "synthetic-corpus-v1" and .summary.total_cases == 36' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "evaluation writes and compares a frozen baseline" {
    baseline="$TEST_CONTENT_DIR/retrieval.baseline.json"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$FIXTURE" --content-dir "$TEST_CONTENT_DIR" \
        --write-baseline "$baseline" --json
    [[ "$status" -eq 0 ]]
    [[ -s "$baseline" ]]

    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$FIXTURE" --content-dir "$TEST_CONTENT_DIR" \
        --baseline "$baseline" --fail-on-regression --json
    [[ "$status" -eq 0 ]]
    run jq -e '
        .baseline_comparison.fixture_match and
        .baseline_comparison.corpus_match and
        (.baseline_comparison.changed_cases | length == 0) and
        (.baseline_comparison.regressions | length == 0) and
        (.baseline_comparison.unchanged_case_count == 36)
    ' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "evaluation rejects an unversioned fixture" {
    invalid_fixture="$TEST_CONTENT_DIR/invalid-fixture.json"
    printf '{"version": 2, "cases": []}\n' > "$invalid_fixture"
    run "$SCRIPTS/evaluate-retrieval" --fixture "$invalid_fixture" --json
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Invalid retrieval fixture"* ]]
}

@test "evaluation rejects an expected path or section absent from the corpus" {
    invalid_fixture="$TEST_CONTENT_DIR/invalid-fixture.json"
    jq -n '
        {
            format: "knowledge-base-retrieval-evaluation",
            version: 1,
            fixture_id: "invalid-locator",
            corpus_id: "synthetic-corpus-v1",
            cases: [{
                id: "missing-path",
                category: "test",
                query: "systemctl restart kb-api",
                expected_sections: [{path: "knowledge/missing.md", section: "Missing"}],
                requires_all_sections: false,
                unanswerable: false
            }]
        }
    ' > "$invalid_fixture"
    run "$SCRIPTS/evaluate-retrieval" --fixture "$invalid_fixture" --json
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"expected locator path not found"* ]]

    jq '.cases[0].expected_sections[0] = {path: "knowledge/operations.md", section: "Missing"}' \
        "$invalid_fixture" > "$TEST_CONTENT_DIR/invalid-section.json"
    run "$SCRIPTS/evaluate-retrieval" --fixture "$TEST_CONTENT_DIR/invalid-section.json" --json
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"expected locator section not found"* ]]
}

@test "fail-on-regression catches rank and evidence regressions while status stays pass" {
    create_test_article "multi.md" '# Multi

## First

shared retrieval phrase

## Second

This section exists but does not match the query.'
    fixture="$TEST_CONTENT_DIR/multi-fixture.json"
    jq -n '
        {
            format: "knowledge-base-retrieval-evaluation",
            version: 1,
            fixture_id: "multi-section-regression",
            corpus_id: "synthetic-corpus-v1",
            cases: [{
                id: "multi",
                category: "test",
                query: "shared retrieval phrase",
                expected_sections: [
                    {path: "knowledge/multi.md", section: "First"},
                    {path: "knowledge/multi.md", section: "Second"}
                ],
                requires_all_sections: false,
                unanswerable: false
            }]
        }
    ' > "$fixture"
    baseline="$TEST_CONTENT_DIR/multi-baseline.json"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$fixture" --content-dir "$TEST_CONTENT_DIR" \
        --write-baseline "$baseline" --json
    [[ "$status" -eq 0 ]]

    mutated_baseline="$TEST_CONTENT_DIR/mutated-baseline.json"
    jq '(.cases[] | select(.id == "multi")) |=
        (.first_relevant_rank = 0 |
         .all_required_evidence = true |
         .matched_required_evidence_count = 2)' \
        "$baseline" > "$mutated_baseline"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$fixture" --content-dir "$TEST_CONTENT_DIR" \
        --baseline "$mutated_baseline" --fail-on-regression --json
    [[ "$status" -ne 0 ]]
    report="$output"
    run jq -e '
        (.cases[] | select(.id == "multi") | .status) == "pass" and
        ([.baseline_comparison.regression_details[] | select(.id == "multi") | .reasons[]]
            | index("first_relevant_rank")) != null and
        ([.baseline_comparison.regression_details[] | select(.id == "multi") | .reasons[]]
            | index("all_required_evidence")) != null and
        ([.baseline_comparison.regression_details[] | select(.id == "multi") | .reasons[]]
            | index("matched_required_evidence_count")) != null
    ' <<< "$report"
    [[ "$status" -eq 0 ]]
}
