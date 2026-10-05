($search_result[0].results // []) as $all_results |
($bounded_result[0].results // []) as $bounded_results |
($question.expected_sections // []) as $expected |
def locator_from_result:
    {path, section: (.locator.section // "top"), number: .locator.number,
     command: .locator.command, routing: (.routing == true)};
def distinct_locators:
    reduce .[] as $result
    ([ ];
        ($result | locator_from_result) as $locator |
        ($locator.path + "\u0000" + $locator.section + "\u0000" +
         ($locator.number // "") + "\u0000" + ($locator.command // "")) as $key |
        if any(.[]; .key == $key) then .
        else . + [{key: $key} + $locator]
        end
    ) | map(del(.key));
($all_results | map(select(.routing != true)) | distinct_locators) as $full_evidence_results |
($all_results | distinct_locators) as $full_ranking_results |
($bounded_results | map(select(.routing != true)) | distinct_locators) as $bounded_evidence_results |
($bounded_results | map(select(.routing == true) | locator_from_result)) as $routing_results |
($expected | map(select((.command // "") != "--alias"))) as $expected_evidence |
($expected | map(select(.command == "--alias"))) as $expected_routing |
($question.unanswerable == true) as $unanswerable |
($question.requires_all_sections == true) as $requires_all |
def locator_matches($actual; $expected):
    ($actual.path == $expected.path) and
    (if ($expected.number // null) != null then
         $actual.number == $expected.number
     elif ($expected.command // null) != null then
         $actual.command == $expected.command
     else
         $actual.section == $expected.section
     end);
($full_evidence_results | length > 0) as $has_retrieved_evidence |
($unanswerable and $has_retrieved_evidence) as $false_positive_retrieval |
([
    $routing_results[] as $routing_result |
    select(any($expected_routing[]; locator_matches($routing_result; .)))
 ] | length > 0) as $routing_success |
($bounded_results | distinct_locators |
    reduce .[] as $result
    ([ ]; {path: $result.path, section: $result.section} as $compact |
        if any(.[]; .path == $compact.path and .section == $compact.section)
        then . else . + [$compact] end
    )) as $top_five |
([
    $expected_evidence[] as $expected_section |
     select(any($bounded_evidence_results[]; locator_matches(.; $expected_section)))
 ] | length) as $matched_count |
([
    $full_ranking_results | to_entries[] | . as $entry |
     select(any($expected_evidence[]; locator_matches($entry.value; .))) |
     (.key + 1)
 ]) as $relevant_ranks |
($relevant_ranks[0] // null) as $first_relevant_rank |
(if $unanswerable then null
 elif ($expected_evidence | length) == 0 then false
 else ($matched_count > 0) end) as $any |
(if $unanswerable then null
 elif ($expected_evidence | length) == 0 then false
 else ($matched_count == ($expected_evidence | length)) end) as $all |
(if $unanswerable then null
 elif $requires_all then $all
 else $any end) as $evidence_success |
(if $unanswerable then null
 elif ($expected_routing | length) > 0 and ($expected_evidence | length) > 0
     then ($routing_success and $evidence_success)
 elif ($expected_routing | length) > 0 then $routing_success
 else $evidence_success end) as $success |
{
    id: $question.id,
    category: $question.category,
    query: $question.query,
    query_mode: ($question.query_mode // "literal"),
    relaxed_query: ($question.relax // false),
    comparison_group: ($question.comparison_group // null),
    retained_terms: ($search_result[0].query_terms // []),
    matching_mode: ($search_result[0].match_mode // "strict"),
    output_budget_bytes: ($search_result[0].max_bytes // null),
    full_omitted_results: ($search_result[0].omitted_results // 0),
    top_five_omitted_results: ($bounded_result[0].omitted_results // 0),
    expected_sections: $expected,
    requires_all_sections: $requires_all,
    unanswerable: $unanswerable,
    status: (if $unanswerable and $has_retrieved_evidence then "false_positive"
             elif $unanswerable then "unanswerable"
             elif $success then "pass"
             else "fail" end),
    any_required_evidence: $any,
    all_required_evidence: $all,
    routing_success: (if $unanswerable then null else $routing_success end),
    false_positive_retrieval: (if $unanswerable then $has_retrieved_evidence else null end),
    matched_required_evidence_count: (if $unanswerable then null else $matched_count end),
    first_relevant_rank: $first_relevant_rank,
    full_ranking_result_count: ($all_results | length),
    full_ranking_response_bytes: ($full_response_bytes | tonumber),
    full_ranking_latency_ms: ($full_latency_ms | tonumber),
    top_five_raw_result_count: ($bounded_results | length),
    top_five_section_count: ($top_five | length),
    top_five_response_bytes: ($bounded_response_bytes | tonumber),
    top_five_latency_ms: ($bounded_latency_ms | tonumber),
    bounded_raw_results: ($bounded_results
        | map({path, section: (.locator.section // "top"),
               number: .locator.number, command: .locator.command,
               line: .locator.line, text})),
    top_five: $top_five,
    failure: (if $false_positive_retrieval then
                  "retrieval returned evidence for an unanswerable query"
              elif $unanswerable or $success then null
              elif ($expected_routing | length) > 0 and ($routing_success | not) then
                  "expected alias routing result was not recovered"
              elif $requires_all then
                  "not all expected sections appear in the top five"
              else "no expected section appears in the top five" end)
}
