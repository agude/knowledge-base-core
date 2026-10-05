#!/usr/bin/env bats

load test_helper

FIXTURE="$BATS_TEST_DIRNAME/fixtures/retrieval-v1/retrieval-v1.json"
FIXTURE_CONTENT="$BATS_TEST_DIRNAME/fixtures/retrieval-v1/content"
QUESTION_FIXTURE="$BATS_TEST_DIRNAME/fixtures/retrieval-question-v1/retrieval-question-v1.json"
PRE_CHANGE_FIXTURE="$BATS_TEST_DIRNAME/fixtures/retrieval-question-v1/retrieval-question-pre-change-v1.json"
QUESTION_CONTENT="$BATS_TEST_DIRNAME/fixtures/retrieval-question-v1/content"
QUESTION_TEMPORAL_JUDGMENTS="$BATS_TEST_DIRNAME/fixtures/retrieval-question-v1/temporal-judgments.json"
QUESTION_COMPARISON_FIXTURE="$BATS_TEST_DIRNAME/fixtures/retrieval-question-v1/retrieval-question-comparison-v1.json"

setup() {
    setup_content_dir
}

@test "evaluation does not count evidence outside the bounded response" {
    for ((i = 1; i <= 5; i++)); do
        create_test_article "alias-$i.md" "---
title: \"Alias $i\"
aliases:
  - \"target route $i\"
---

# Alias $i

Routing record."
    done
    create_test_article "evidence.md" '# Evidence

## Required

target

## Other

route'
    fixture="$TEST_CONTENT_DIR/alias-fixture.json"
    jq -n '
        {
            format: "knowledge-base-retrieval-evaluation",
            version: 1,
            fixture_id: "bounded-routing",
            corpus_id: "synthetic-corpus-v1",
            cases: [{
                id: "aliases-hide-evidence",
                category: "routing",
                query: "Where is the target route?",
                query_mode: "question",
                expected_sections: [{path: "knowledge/evidence.md", section: "Required"}],
                requires_all_sections: false,
                unanswerable: false
            }]
        }
    ' > "$fixture"

    run "$SCRIPTS/evaluate-retrieval" --fixture "$fixture" \
        --content-dir "$TEST_CONTENT_DIR" --json
    [[ "$status" -eq 0 ]]
    run jq -e '
        (.cases[0].status == "fail") and
        (.cases[0].first_relevant_rank == 6) and
        (.cases[0].matched_required_evidence_count == 0) and
        (.cases[0].top_five | all(.[]; .path != "knowledge/evidence.md"))
    ' <<< "$output"
    [[ "$status" -eq 0 ]]
}

teardown() { teardown_content_dir; }

copy_literal_fixture_content() {
    cp -R "$FIXTURE_CONTENT/knowledge/." "$TEST_CONTENT_DIR/knowledge/"
}

write_single_case_fixture() {
    local fixture="$1" case_id="$2" query="$3" expected_path="$4"
    local expected_section="$5" unanswerable="$6"
    jq -n \
        --arg case_id "$case_id" \
        --arg query "$query" \
        --arg expected_path "$expected_path" \
        --arg expected_section "$expected_section" \
        --argjson unanswerable "$unanswerable" '
        {
            format: "knowledge-base-retrieval-evaluation",
            version: 1,
            fixture_id: "focused-retrieval-v1",
            corpus_id: "focused-corpus-v1",
            cases: [{
                id: $case_id,
                category: "focused-test",
                query: $query,
                expected_sections: (if $unanswerable then [] else
                    [{path: $expected_path, section: $expected_section}]
                    end),
                requires_all_sections: false,
                unanswerable: $unanswerable
            }]
        }
    ' > "$fixture"
}

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
    copy_literal_fixture_content
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
        .measurement.coverage_unit == "distinct search locators (path, section, number/command) from the bounded top-five response" and
        .measurement.full_ranking_command == "search --json --limit 0 --per-file 0 QUERY" and
        .measurement.top_five_command == "search --json --limit 5 --per-file 0 QUERY" and
        .summary.total_cases == 36 and
        .summary.answerable_cases == 31 and
        .summary.unanswerable_cases == 5 and
        .summary.passed_cases == 18 and
        .summary.failed_cases == 14 and
        .summary.any_required_evidence_cases == 18 and
        .summary.all_required_evidence_cases == 18 and
        .summary.false_positive_unanswerable_cases == 1 and
        .summary.false_positive_unanswerable_rate == 0.2 and
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
            (.status == "unanswerable" or .status == "false_positive") and
            (.false_positive_retrieval | type) == "boolean" and
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
        and
        ((.cases[] | select(.id == "absent-02")) |
            .status == "false_positive" and
            .false_positive_retrieval == true and
            .failure == "retrieval returned evidence for an unanswerable query")
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

@test "evaluation runs committed question-mode fixture" {
    question_root="$TEST_CONTENT_DIR/question-root"
    mkdir -p "$question_root"
    cp -R "$QUESTION_CONTENT/." "$question_root/"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$QUESTION_FIXTURE" --content-dir "$question_root" \
        --baseline "$BATS_TEST_DIRNAME/fixtures/retrieval-question-v1/retrieval-question-v1.baseline.json" \
        --json
    [[ "$status" -eq 0 ]]
    run jq -e '
        .evaluation_role == "post_implementation" and
        .summary.total_cases == 10 and
        .summary.answerable_cases == 8 and
        .summary.unanswerable_cases == 2 and
        .summary.query_modes == [{"mode": "question", "cases": 10}] and
        .summary.routing_success_cases == 1 and
        (.cases[] | select(.id == "question-normalization-01") |
            .query_mode == "question" and
            .retained_terms == ["restart", "--no-verify", "2026-10-03", "/srv/backups/kb"] and
            .status == "pass") and
        (.cases[] | select(.id == "question-unanswerable-01") |
            .status == "unanswerable" and .false_positive_retrieval == false) and
        (.cases[] | select(.id == "question-alias-routing-01") |
            .status == "pass" and
            .routing_success == true and
            .any_required_evidence == false and
            .all_required_evidence == false and
            .matched_required_evidence_count == 0 and
            .first_relevant_rank == null) and
        (.cases[] | select(.id == "temporal-current-01") |
            .status == "pass" and .first_relevant_rank == 1) and
        (.cases[] | select(.id == "temporal-historical-01") |
            .status == "pass" and .first_relevant_rank == 1) and
        .baseline_comparison.fixture_match and
        .baseline_comparison.corpus_match and
        (.baseline_comparison.regressions | length == 0)
    ' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "evaluation freezes a pre-change literal control on the question corpus" {
    question_root="$TEST_CONTENT_DIR/question-root"
    mkdir -p "$question_root"
    cp -R "$QUESTION_CONTENT/." "$question_root/"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$PRE_CHANGE_FIXTURE" --content-dir "$question_root" \
        --baseline "$BATS_TEST_DIRNAME/fixtures/retrieval-question-v1/retrieval-question-pre-change-v1.baseline.json" \
        --json
    [[ "$status" -eq 0 ]]
    run jq -e '
        .evaluation_role == "pre_change" and
        .summary.query_modes == [{"mode": "literal", "cases": 10}] and
        .summary.answerable_cases == 8 and
        .summary.passed_cases < .summary.answerable_cases and
        (.cases[] | select(.id == "question-backup-location-01") |
            .query_mode == "literal" and .status == "fail") and
        .baseline_comparison.fixture_match and
        .baseline_comparison.corpus_match and
        .baseline_comparison.evaluation_role_match and
        (.baseline_comparison.regressions | length == 0)
    ' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "evaluation reports strict and relaxed comparison gains separately" {
    question_root="$TEST_CONTENT_DIR/question-root"
    mkdir -p "$question_root"
    cp -R "$QUESTION_CONTENT/." "$question_root/"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$QUESTION_COMPARISON_FIXTURE" --content-dir "$question_root" \
        --baseline "$BATS_TEST_DIRNAME/fixtures/retrieval-question-v1/retrieval-question-comparison-v1.baseline.json" \
        --json
    [[ "$status" -eq 0 ]]
    run jq -e '
        .evaluation_role == "comparison" and
        .summary.total_cases == 6 and
        .summary.query_modes == [
            {"mode": "literal", "cases": 1},
            {"mode": "question", "cases": 5}
        ] and
        .summary.relaxation.compared_groups == 2 and
        .summary.relaxation.discovery_gain_groups == 1 and
        .summary.relaxation.added_false_positive_groups == 1 and
        (.summary.comparison_groups | all(.[];
            .strict_case_count == 1 and .relaxed_case_count == 1)) and
        (.cases[] | select(.id == "question-relaxation-strict-01") |
            .status == "fail" and .relaxed_query == false) and
        (.cases[] | select(.id == "question-relaxation-enabled-01") |
            .status == "pass" and .relaxed_query == true) and
        (.cases[] | select(.id == "question-relaxation-abstention-strict-01") |
            .status == "unanswerable" and .false_positive_retrieval == false) and
        (.cases[] | select(.id == "question-relaxation-abstention-enabled-01") |
            .status == "false_positive" and .false_positive_retrieval == true)
        and .baseline_comparison.fixture_match
        and .baseline_comparison.corpus_match
        and (.baseline_comparison.regressions | length == 0)
    ' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "temporal answer judgments separate retrieval from current-claim selection" {
    run jq -e '
        .format == "knowledge-base-temporal-answer-judgments" and
        .version == 1 and
        .fixture_id == "synthetic-question-v1" and
        (.judgments | length == 2) and
        (all(.judgments[];
            (.answer_judgment == "manual") and
            (.expected_current_claim | length > 0) and
            (.historical_claims | length > 0) and
            (.supporting_sections | length > 0) and
            (.abstain_if | length > 0)
        ))
    ' "$QUESTION_TEMPORAL_JUDGMENTS"
    [[ "$status" -eq 0 ]]
}

@test "evaluation reports an optional output byte budget" {
    question_root="$TEST_CONTENT_DIR/question-root"
    mkdir -p "$question_root"
    cp -R "$QUESTION_CONTENT/." "$question_root/"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$QUESTION_FIXTURE" --content-dir "$question_root" \
        --max-bytes 2000 --json
    [[ "$status" -eq 0 ]]
    run jq -e '
        .summary.output_budget_bytes == 2000 and
        .summary.full_omitted_results_total > 0 and
        .summary.top_five_omitted_results_total > 0 and
        all(.cases[]; .output_budget_bytes == 2000)
    ' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "fail-on-regression catches new false-positive retrieval" {
    create_test_article "false-positive.md" '# False Positive

## Evidence

obsolete setting is enabled'
    fixture="$TEST_CONTENT_DIR/false-positive-fixture.json"
    write_single_case_fixture "$fixture" focused-absent \
        "obsolete setting" "" "" true
    baseline="$TEST_CONTENT_DIR/false-positive-baseline.json"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$fixture" --content-dir "$TEST_CONTENT_DIR" \
        --write-baseline "$baseline" --json
    [[ "$status" -eq 0 ]]

    mutated_baseline="$TEST_CONTENT_DIR/mutated-false-positive-baseline.json"
    jq '(.cases[] | select(.id == "focused-absent") | .false_positive_retrieval) = false' \
        "$baseline" > "$mutated_baseline"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$fixture" --content-dir "$TEST_CONTENT_DIR" \
        --baseline "$mutated_baseline" --fail-on-regression --json
    [[ "$status" -ne 0 ]]
    run jq -e '
        ([.baseline_comparison.regression_details[] | select(.id == "focused-absent") | .reasons[]]
            | index("false_positive_retrieval")) != null
    ' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "evaluation can select content independently of KB_CONTENT_DIR" {
    create_test_article "content-root.md" '# Content Root

## Evidence

focused content root evidence'
    fixture="$TEST_CONTENT_DIR/content-root-fixture.json"
    write_single_case_fixture "$fixture" content-root \
        "focused content root" knowledge/content-root.md Evidence false
    run env -u KB_CONTENT_DIR "$SCRIPTS/evaluate-retrieval" \
        --fixture "$fixture" --content-dir "$TEST_CONTENT_DIR" --json
    [[ "$status" -eq 0 ]]
    run jq -e '.corpus_id == "focused-corpus-v1" and
        .summary.total_cases == 1 and .summary.passed_cases == 1' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "evaluation writes and compares a frozen baseline" {
    create_test_article "baseline.md" '# Baseline

## Evidence

focused baseline evidence'
    fixture="$TEST_CONTENT_DIR/baseline-fixture.json"
    write_single_case_fixture "$fixture" baseline \
        "focused baseline" knowledge/baseline.md Evidence false
    baseline="$TEST_CONTENT_DIR/retrieval.baseline.json"
    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$fixture" --content-dir "$TEST_CONTENT_DIR" \
        --write-baseline "$baseline" --json
    [[ "$status" -eq 0 ]]
    [[ -s "$baseline" ]]

    run "$SCRIPTS/evaluate-retrieval" \
        --fixture "$fixture" --content-dir "$TEST_CONTENT_DIR" \
        --baseline "$baseline" --fail-on-regression --json
    [[ "$status" -eq 0 ]]
    run jq -e '
        .baseline_comparison.fixture_match and
        .baseline_comparison.corpus_match and
        (.baseline_comparison.changed_cases | length == 0) and
        (.baseline_comparison.regressions | length == 0) and
        (.baseline_comparison.unchanged_case_count == 1)
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
    create_test_article "operations.md" '# Operations

## Restart

Restart documentation.'
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
