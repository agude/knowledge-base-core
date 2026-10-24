# Interface surface

Every option, subcommand, input, and exit code of each executable, with the
tests that cover it. `test_harness.py::test_surface_inventory` checks that
every executable has rows and that every row names existing tests.

Edge input. Every reading command runs against every input class in
`test_edge_input.py::test_edge` (parameter `<class>-<command>`). Contract: the
exit code and the facts reported. `unreadable` is skipped when running as root.

| Command | empty | missing-dirs | malformed-front-matter | crlf | non-ascii | no-trailing-newline | spaces | symlinks | unreadable |
|---|---|---|---|---|---|---|---|---|---|
| `search` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `section` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `toc` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `stale` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `pending` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `status` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `context` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `questions` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `lint` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |
| `session-context` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` | `test_edge` |

## archive

| Entry | Tests |
|---|---|
| `--all` | `test_archive.py::test_archive_all`, `test_archive.py::test_archive_all_with_nothing_pending` |
| `--no-commit` | `test_archive.py::test_archive_one`, `test_archive.py::test_archive_several`, `test_archive.py::test_archive_all`, `test_archive.py::test_archive_missing` |
| `--batch` | `test_batch.py::test_batch_snapshot_complete_defer`, `test_batch.py::test_batch_changed_input`, `test_batch.py::test_budgeted_batch_rejections`, `test_batch.py::test_repeat_completion` |
| `--disposition` | `test_archive.py::test_archive_disposition_errors`, `test_archive.py::test_archive_disposition_recorded`, `test_batch.py::test_batch_snapshot_complete_defer`, `test_batch.py::test_batch_changed_input` |
| `--destination` | `test_archive.py::test_archive_disposition_errors`, `test_archive.py::test_archive_disposition_recorded`, `test_batch.py::test_incorporated_completion`, `test_batch.py::test_batch_status_report` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_archive.py::test_archive_all`, `test_archive.py::test_archive_all_with_nothing_pending`, `test_archive.py::test_archive_commit_ignores_legacy_broken_links` |
| exit 1 | `test_archive.py::test_archive_disposition_errors`, `test_archive.py::test_archive_existing_destination`, `test_archive.py::test_archive_missing` |
| FILENAME ... | `test_archive.py::test_archive_several` |

## ask

| Entry | Tests |
|---|---|
| `--title` | `test_questions.py::test_ask_creates_question`, `test_questions.py::test_ask_context`, `test_questions.py::test_ask_context_missing`, `test_questions.py::test_ask_body` |
| `--context` | `test_questions.py::test_ask_context`, `test_questions.py::test_ask_context_missing`, `test_lib.py::test_context_resolution` |
| `--body` | `test_questions.py::test_ask_body`, `test_questions.py::test_ask_body_from_stdin`, `test_questions.py::test_ask_body_that_looks_like_an_echo_option`, `test_lib.py::test_option_arguments` |
| `--source` | `test_questions.py::test_ask_escapes_title` |
| `--no-commit` | `test_questions.py::test_ask_creates_question`, `test_questions.py::test_ask_context`, `test_questions.py::test_ask_context_missing`, `test_questions.py::test_ask_body` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_questions.py::test_ask_body`, `test_questions.py::test_ask_body_from_stdin`, `test_questions.py::test_ask_body_that_looks_like_an_echo_option` |
| exit 1 | `test_questions.py::test_ask_context_missing`, `test_questions.py::test_ask_requires_title`, `test_lib.py::test_context_resolution` |

## batch

| Entry | Tests |
|---|---|
| `--max-bytes` | `test_batch.py::test_budgeted_batch_rejections`, `test_batch.py::test_budgeted_recovery`, `test_batch.py::test_batch_byte_budget`, `test_batch.py::test_batch_bounds_oversized_report` |
| `--files` | `test_batch.py::test_batch_explicit_subset`, `test_batch.py::test_batch_invalid_selection`, `test_batch.py::test_batch_budget_errors`, `test_batch.py::test_batch_exact_fit` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 1 | `test_batch.py::test_batch_changed_input`, `test_batch.py::test_batch_status_invalid_disposition`, `test_batch.py::test_batch_usage_errors` |
|  | `test_batch.py::test_batch_snapshot_complete_defer` |
|  | `test_batch.py::test_batch_status_report` |
|  | `test_batch.py::test_batch_snapshot_complete_defer` |

## commit

| Entry | Tests |
|---|---|
| `--message` | `test_commit.py::test_commit_long_option` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_commit.py::test_commit_all_areas`, `test_commit.py::test_commit_archived_observation`, `test_commit.py::test_commit_article` |
| exit 1 | `test_commit.py::test_commit_ignores_files_outside_content_areas`, `test_commit.py::test_commit_lint_failure`, `test_commit.py::test_commit_message_requires_argument` |

## context

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_status_context.py::test_context_empty`, `test_status_context.py::test_context_mixed`, `test_status_context.py::test_context_pending` |

## doctor

| Entry | Tests |
|---|---|
| `--require` | `test_doctor.py::test_doctor_passing_setup`, `test_doctor.py::test_doctor_adapters`, `test_doctor.py::test_doctor_node_versions`, `test_doctor.py::test_doctor_missing_content_root` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_doctor.py::test_doctor_node_versions`, `test_doctor.py::test_doctor_session_directory` |
| exit 1 | `test_doctor.py::test_doctor_argument_errors`, `test_doctor.py::test_doctor_node_versions`, `test_doctor.py::test_doctor_session_directory` |

## evaluate-retrieval

| Entry | Tests |
|---|---|
| `--fixture` | `test_evaluate_retrieval.py::test_bounded_response`, `test_evaluate_retrieval.py::test_literal_fixture_report`, `test_evaluate_retrieval.py::test_question_fixture_report`, `test_evaluate_retrieval.py::test_pre_change_control` |
| `--content-dir` | `test_evaluate_retrieval.py::test_bounded_response`, `test_evaluate_retrieval.py::test_literal_fixture_report`, `test_evaluate_retrieval.py::test_question_fixture_report`, `test_evaluate_retrieval.py::test_pre_change_control` |
| `--baseline` | `test_evaluate_retrieval.py::test_literal_fixture_report`, `test_evaluate_retrieval.py::test_question_fixture_report`, `test_evaluate_retrieval.py::test_pre_change_control`, `test_evaluate_retrieval.py::test_comparison_fixture` |
| `--write-baseline` | `test_evaluate_retrieval.py::test_false_positive_regression`, `test_evaluate_retrieval.py::test_write_and_compare_baseline`, `test_evaluate_retrieval.py::test_rank_and_evidence_regression` |
| `--fail-on-regression` | `test_evaluate_retrieval.py::test_false_positive_regression`, `test_evaluate_retrieval.py::test_write_and_compare_baseline`, `test_evaluate_retrieval.py::test_rank_and_evidence_regression` |
| `--max-bytes` | `test_evaluate_retrieval.py::test_output_budget`, `test_evaluate_retrieval.py::test_argument_errors` |
| `--json` | `test_evaluate_retrieval.py::test_question_fixture_report` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_evaluate_retrieval.py::test_comparison_fixture`, `test_evaluate_retrieval.py::test_content_dir_without_env`, `test_evaluate_retrieval.py::test_literal_fixture_report` |
| exit 1 | `test_evaluate_retrieval.py::test_argument_errors` |

## init

| Entry | Tests |
|---|---|
| `--path` | `test_init.py::test_init_with_path`, `test_init.py::test_init_twice`, `test_init.py::test_init_relative_path`, `test_init.py::test_init_existing_partial_directory` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_init.py::test_init_with_path` |
| exit 1 | `test_init.py::test_init_path_requires_argument` |

## install

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_install.py::test_install_fresh` |
| exit 1 | `test_help.py::test_unknown_option` |

## lint

| Entry | Tests |
|---|---|
| `--path` | `test_lint.py::test_lint_corrections_fixture`, `test_lint.py::test_lint_scope` |
| `--file` | `test_lint.py::test_lint_valid_links`, `test_lint.py::test_lint_broken_links`, `test_lint.py::test_lint_ignores_external_and_fenced`, `test_lint.py::test_lint_batch_future_source` |
| `--max-lines` | `test_lint.py::test_lint_thresholds`, `test_lint.py::test_lint_argument_errors` |
| `--strict` | `test_lint.py::test_lint_thresholds` |
| `--batch` | `test_lint.py::test_lint_batch_future_source`, `test_lint.py::test_lint_batch_deferred_source` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_lint.py::test_lint_batch_future_source`, `test_lint.py::test_lint_corrections_fixture`, `test_lint.py::test_lint_good` |
| exit 1 | `test_lint.py::test_lint_argument_errors`, `test_lint.py::test_lint_batch_deferred_source`, `test_lint.py::test_lint_batch_future_source` |

## observe

| Entry | Tests |
|---|---|
| `--title` | `test_observe.py::test_observe_writes_front_matter`, `test_observe.py::test_observe_source`, `test_observe.py::test_observe_ignores_knowledge_observe`, `test_observe.py::test_observe_body_from_stdin` |
| `--body` | `test_observe.py::test_observe_writes_front_matter`, `test_observe.py::test_observe_source`, `test_observe.py::test_observe_ignores_knowledge_observe`, `test_observe.py::test_observe_requires_title` |
| `--source` | `test_observe.py::test_observe_source` |
| `--no-commit` | `test_observe.py::test_observe_writes_front_matter`, `test_observe.py::test_observe_source`, `test_observe.py::test_observe_ignores_knowledge_observe`, `test_observe.py::test_observe_requires_title` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_observe.py::test_observe_body_from_stdin`, `test_observe.py::test_observe_cleans_up`, `test_observe.py::test_observe_escapes_title` |
| exit 1 | `test_observe.py::test_observe_lock_wait_expires`, `test_observe.py::test_observe_rejects_bad_lock_wait`, `test_observe.py::test_observe_requires_body` |

## pending

| Entry | Tests |
|---|---|
| `--full` | `test_pending.py::test_pending_missing_directory`, `test_pending.py::test_pending_empty`, `test_pending.py::test_pending_listing`, `test_pending.py::test_nested_observations` |
| `--count` | `test_pending.py::test_pending_missing_directory`, `test_pending.py::test_pending_empty`, `test_pending.py::test_pending_listing`, `test_pending.py::test_nested_observations` |
| `--preview` | `test_pending.py::test_pending_missing_directory`, `test_pending.py::test_preview_metrics`, `test_pending.py::test_preview_malformed_and_large`, `test_pending.py::test_nested_observations` |
| `--max-bytes` | `test_pending.py::test_preview_byte_budget`, `test_pending.py::test_preview_zero_budget`, `test_pending.py::test_preview_invalid_budget`, `test_pending.py::test_preview_bounds_oversized_report` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_pending.py::test_nested_observations`, `test_pending.py::test_pending_empty`, `test_pending.py::test_pending_listing` |
| exit 1 | `test_pending.py::test_pending_unknown_option`, `test_pending.py::test_preview_invalid_budget`, `test_lib.py::test_decimal_parsing` |

## questions

| Entry | Tests |
|---|---|
| `--path` | `test_questions.py::test_questions_path_filter`, `test_questions.py::test_questions_path_filter_no_match`, `test_questions.py::test_questions_path_filter_resolves_bare_name`, `test_lib.py::test_scripts_refuse_escaping_paths` |
| `--file` | `test_questions.py::test_questions_file`, `test_questions.py::test_questions_file_resolved`, `test_questions.py::test_questions_file_errors`, `test_questions.py::test_resolve_with_answer` |
| `--full` | `test_questions.py::test_questions_full_and_all` |
| `--all` | `test_questions.py::test_questions_full_and_all` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_questions.py::test_questions_empty`, `test_questions.py::test_questions_file`, `test_questions.py::test_questions_file_resolved` |
| exit 1 | `test_questions.py::test_questions_file_errors`, `test_questions.py::test_questions_unknown_option`, `test_lib.py::test_context_resolution` |

## resolve

| Entry | Tests |
|---|---|
| `--file` | `test_questions.py::test_questions_file`, `test_questions.py::test_questions_file_resolved`, `test_questions.py::test_questions_file_errors`, `test_questions.py::test_resolve_with_answer` |
| `--answer` | `test_questions.py::test_resolve_with_answer`, `test_questions.py::test_resolve_answer_from_stdin_and_commit`, `test_pretool_allow.py::test_resolve_cannot_append_outside` |
| `--no-commit` | `test_questions.py::test_ask_creates_question`, `test_questions.py::test_ask_context`, `test_questions.py::test_ask_context_missing`, `test_questions.py::test_ask_body` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_questions.py::test_resolve_answer_from_stdin_and_commit`, `test_questions.py::test_resolve_with_answer`, `test_questions.py::test_resolve_without_answer` |
| exit 1 | `test_questions.py::test_resolve_argument_errors`, `test_questions.py::test_resolve_missing`, `test_lib.py::test_scripts_refuse_escaping_paths` |

## search

| Entry | Tests |
|---|---|
| `--query` | `test_search.py::test_question_preserves_identifiers`, `test_search.py::test_question_terms`, `test_search.py::test_question_punctuation_and_unicode`, `test_search.py::test_question_errors` |
| `--relax` | `test_search.py::test_question_relaxation` |
| `--explain` | `test_search.py::test_question_explanation`, `test_search.py::test_combined_limits` |
| `--limit` | `test_search.py::test_arguments`, `test_search.py::test_duplicate_heading_numbers`, `test_search.py::test_title_above_body`, `test_search.py::test_exact_title_above_repetition` |
| `--per-file` | `test_search.py::test_arguments`, `test_search.py::test_duplicate_heading_numbers`, `test_search.py::test_exact_title_above_repetition`, `test_search.py::test_repeated_evidence_once` |
| `--path` | `test_search.py::test_path_and_topic`, `test_search.py::test_empty_scope_intersection`, `test_stale.py::test_stale_path`, `test_stale.py::test_stale_sources` |
| `--topic` | `test_search.py::test_path_and_topic`, `test_search.py::test_empty_scope_intersection` |
| `--corpus` | `test_search.py::test_corpus_filter` |
| `--archive` | `test_search.py::test_archive_and_questions`, `test_search.py::test_source_and_archive_provenance`, `test_search.py::test_question_records` |
| `--files` | `test_search.py::test_title_above_body`, `test_search.py::test_heading_above_body`, `test_search.py::test_hidden_counts` |
| `--json` | `test_search.py::test_match_in_article`, `test_search.py::test_match_in_pending`, `test_search.py::test_no_match`, `test_search.py::test_multiple_terms` |
| `--text-only` | `test_search.py::test_labels`, `test_search.py::test_text_budget_signals_truncation`, `test_section.py::test_section_text_only`, `test_section.py::test_section_top_and_title` |
| `--max-bytes` | `test_search.py::test_arguments`, `test_search.py::test_leading_zero_budget`, `test_search.py::test_empty_scope_intersection`, `test_search.py::test_json_budget_complete_records` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_section.py::test_crlf_metadata` |
| exit 1 | `test_search.py::test_arguments`, `test_search.py::test_budget_below_envelope` |
| TERM ... | `test_search.py::test_multiple_terms` |
| `--` before terms | `test_search.py::test_arguments` |

## section

| Entry | Tests |
|---|---|
| `--file` | `test_section.py::test_section_number`, `test_section.py::test_section_heading`, `test_section.py::test_section_file_resolution`, `test_section.py::test_section_default_labels` |
| `--number` | `test_section.py::test_section_number`, `test_section.py::test_section_file_resolution`, `test_section.py::test_section_default_labels`, `test_section.py::test_section_text_only` |
| `--heading` | `test_section.py::test_section_heading`, `test_section.py::test_section_conflicts`, `test_section.py::test_section_json_full`, `test_section.py::test_section_reference_formats_agree` |
| `--top` | `test_section.py::test_section_top_and_title`, `test_section.py::test_section_reference_formats_agree` |
| `--title` | `test_section.py::test_section_top_and_title`, `test_section.py::test_section_title_missing`, `test_section.py::test_section_reference_formats_agree`, `test_lib.py::test_out_of_range_section_ttl` |
| `--exact` | `test_section.py::test_section_heading`, `test_section.py::test_section_reference_formats_agree`, `test_fences.py::test_section_exact_after_closing_hashes` |
| `--json` | `test_section.py::test_section_conflicts`, `test_section.py::test_section_top_and_title`, `test_section.py::test_section_json_full`, `test_section.py::test_section_json_metadata` |
| `--text-only` | `test_section.py::test_section_text_only`, `test_section.py::test_section_top_and_title`, `test_section.py::test_text_budget_truncates_and_cleans_up`, `test_section.py::test_text_budget_large_prefix` |
| `--references` | `test_section.py::test_section_references`, `test_section.py::test_section_references_budget` |
| `--section-references` | `test_section.py::test_section_reference_formats_agree` |
| `--max-bytes` | `test_section.py::test_section_references_budget`, `test_section.py::test_section_invalid_budget`, `test_section.py::test_json_budget_preserves_metadata`, `test_section.py::test_json_budget_serializes_candidates` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_section.py::test_crlf_metadata`, `test_fences.py::test_fenced_comments_keep_numbering`, `test_fences.py::test_section_exact_after_closing_hashes` |
| exit 1 | `test_lib.py::test_scripts_refuse_escaping_paths`, `test_pretool_allow.py::test_section_cannot_read_outside` |

## session-append

| Entry | Tests |
|---|---|
| `--file` | `test_session_core.py::test_append_messages`, `test_session_core.py::test_append_to_missing_file`, `test_session_core.py::test_append_argument_errors`, `test_session_core.py::test_append_empty_message` |
| `--session-id` | `test_session_core.py::test_session_init`, `test_session_core.py::test_persisted_initialization`, `test_session_core.py::test_init_before_sweep`, `test_session_core.py::test_init_sweep_output` |
| `--role` | `test_session_core.py::test_persisted_initialization`, `test_session_core.py::test_append_messages`, `test_session_core.py::test_append_by_session_id`, `test_session_core.py::test_append_to_missing_file` |
| `--message` | `test_session_core.py::test_persisted_initialization`, `test_session_core.py::test_append_messages`, `test_session_core.py::test_append_by_session_id`, `test_session_core.py::test_append_to_missing_file` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_core.py::test_persisted_initialization` |
| exit 1 | `test_session_core.py::test_append_argument_errors`, `test_session_core.py::test_append_creation_failure`, `test_session_core.py::test_append_requires_target` |

## session-context

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_core.py::test_session_context` |

## session-file

| Entry | Tests |
|---|---|
| `--session-id` | `test_session_core.py::test_session_init`, `test_session_core.py::test_persisted_initialization`, `test_session_core.py::test_init_before_sweep`, `test_session_core.py::test_init_sweep_output` |
| `--create` | `test_session_core.py::test_session_file` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_core.py::test_session_file` |
| exit 1 | `test_session_core.py::test_session_file_errors` |

## session-flush

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_core.py::test_flush_min_messages`, `test_session_core.py::test_flush_threshold`, `test_session_core.py::test_flush_without_argument` |
| exit 1 | `test_session_core.py::test_flush_malformed_buffer`, `test_session_core.py::test_flush_min_messages`, `test_session_core.py::test_flush_observe_failure` |
| exit 130 | `test_session_core.py::test_flush_interrupted_while_blocked`, `test_session_core.py::test_flush_signal_to_process_only` |
| FILE | `test_session_core.py::test_flush_threshold` |
| `--preserve-initialization` | `test_session_core.py::test_flush_preserve_initialization` |

## session-init

| Entry | Tests |
|---|---|
| `--session-id` | `test_session_core.py::test_session_init`, `test_session_core.py::test_persisted_initialization`, `test_session_core.py::test_init_before_sweep`, `test_session_core.py::test_init_sweep_output` |
| `--persist-initialization` | `test_session_core.py::test_persisted_initialization`, `test_session_core.py::test_init_before_sweep`, `test_session_core.py::test_flush_clears_marker` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_core.py::test_init_sweep_output`, `test_session_core.py::test_persisted_initialization`, `test_session_core.py::test_session_init` |
| exit 1 | `test_session_core.py::test_init_rejects_bad_ids` |

## stale

| Entry | Tests |
|---|---|
| `--days` | `test_stale.py::test_stale_days`, `test_stale.py::test_stale_days_overrides_ttl`, `test_stale.py::test_stale_argument_errors` |
| `--path` | `test_stale.py::test_stale_path`, `test_stale.py::test_stale_sources` |
| `--sections` | `test_stale.py::test_stale_sections` |
| `--count` | `test_stale.py::test_stale_count`, `test_stale.py::test_stale_count_clean`, `test_stale.py::test_freshness_boundary_shared`, `test_stale.py::test_stale_sections` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_stale.py::test_stale_argument_errors`, `test_stale.py::test_stale_count`, `test_stale.py::test_stale_count_clean` |
| exit 1 | `test_stale.py::test_stale_argument_errors`, `test_stale.py::test_stale_path` |

## status

| Entry | Tests |
|---|---|
| `--brief` | `test_status_context.py::test_status_brief`, `test_status_context.py::test_status_brief_stale`, `test_smoke.py::test_status_brief_counts` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_status_context.py::test_status_brief`, `test_status_context.py::test_status_brief_stale`, `test_status_context.py::test_status_counts` |
| exit 1 | `test_status_context.py::test_status_unknown_option` |

## sync

| Entry | Tests |
|---|---|
| `--status` | `test_sync.py::test_sync_status`, `test_sync.py::test_sync_status_in_sync`, `test_sync.py::test_sync_fetch_failure`, `test_sync.py::test_sync_missing_tracking_ref` |
| `--no-push` | `test_sync.py::test_sync_no_push` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_sync.py::test_sync_in_sync`, `test_sync.py::test_sync_no_push`, `test_sync.py::test_sync_pulls` |
| exit 1 | `test_sync.py::test_sync_fetch_failure`, `test_sync.py::test_sync_leaves_conflicts`, `test_sync.py::test_sync_missing_tracking_ref` |

## toc

| Entry | Tests |
|---|---|
| `--depth` | `test_toc.py::test_toc_depth`, `test_toc.py::test_toc_flat`, `test_toc.py::test_toc_map_is_compact`, `test_toc.py::test_toc_h3_counter_resets` |
| `--path` | `test_toc.py::test_toc_path`, `test_pretool_allow.py::test_toc_cannot_walk_outside`, `test_lib.py::test_scripts_refuse_escaping_paths` |
| `--flat` | `test_toc.py::test_toc_flat` |
| `--dirs` | `test_toc.py::test_toc_dirs`, `test_pretool_allow.py::test_toc_cannot_walk_outside` |
| `--map` | `test_toc.py::test_toc_map`, `test_toc.py::test_toc_map_is_compact` |
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_toc.py::test_toc_argument_errors`, `test_toc.py::test_toc_article_without_h1`, `test_toc.py::test_toc_default_depth` |
| exit 1 | `test_toc.py::test_toc_argument_errors`, `test_toc.py::test_toc_path`, `test_lib.py::test_scripts_refuse_escaping_paths` |

## hooks/pre-commit

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_pre_commit.py::test_ignores_commits_without_articles`, `test_pre_commit.py::test_no_restamp_today`, `test_pre_commit.py::test_oversized_section_warns` |
| exit 1 | `test_pre_commit.py::test_lints_non_ascii_name`, `test_pre_commit.py::test_no_front_matter_body_untouched`, `test_pre_commit.py::test_rejection_leaves_tree_untouched` |
| staged articles | `test_pre_commit.py::test_stamps_updated` |

## adapters/claude/pretool-allow

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_pretool_allow.py::test_approves_bare_invocation`, `test_pretool_allow.py::test_rejects` |
| stdin JSON | `test_pretool_allow.py::test_rejects` |

## adapters/claude/session-start

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_start.py::test_session_start_content_claude_md`, `test_session_start.py::test_session_start_content_instructions`, `test_session_start.py::test_session_start_creates_buffer` |
| stdin JSON | `test_session_start.py::test_session_start_creates_buffer` |

## adapters/claude/session-prompt

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_flow.py::test_buffer_persists_after_stop` |
| exit 1 | `test_adapters.py::test_buffer_creation_failure` |
| stdin JSON | `test_session_flow.py::test_buffer_accumulates` |

## adapters/claude/session-stop

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_flow.py::test_buffer_persists_after_stop` |
| exit 1 | `test_adapters.py::test_buffer_creation_failure` |
| stdin JSON | `test_session_flow.py::test_buffer_accumulates` |

## adapters/claude/session-end

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_session_flow.py::test_session_end_flushes` |
| stdin JSON | `test_session_flow.py::test_session_end_flushes` |

## adapters/codex/session-start

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_adapters.py::test_codex_session_start` |
| stdin JSON | `test_adapters.py::test_codex_session_start` |

## adapters/codex/session-prompt

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_adapters.py::test_codex_off_without_start` |
| exit 1 | `test_adapters.py::test_buffer_creation_failure` |
| stdin JSON | `test_adapters.py::test_codex_multi_turn` |

## adapters/codex/session-stop

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_adapters.py::test_codex_off_without_start` |
| exit 1 | `test_adapters.py::test_buffer_creation_failure` |
| stdin JSON | `test_adapters.py::test_codex_multi_turn` |

## adapters/codex/session-end

| Entry | Tests |
|---|---|
| `--help` | `test_help.py::test_help` |
| unknown option | `test_help.py::test_unknown_option` |
| exit 0 | `test_adapters.py::test_codex_multi_turn` |
| stdin JSON | `test_adapters.py::test_codex_multi_turn` |

