"""Tests for query normalization, unit construction, and ranking."""

import pytest

from kb import search
from kb.model import parse


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("Restart NAS now", ["restart", "nas", "now"]),
        ("verified 2026-10-24.", ["verified", "2026-10-24"]),
        ("run --no-verify here", ["run", "--no-verify", "here"]),
        ("see /srv/backups/kb.", ["see", "/srv/backups/kb"]),
        ("knowledge/infra/nas.md", ["knowledge/infra/nas.md"]),
        ("ccrs-to-sqlite", ["ccrs", "to", "sqlite"]),
        ("don't stop", ["don't", "stop"]),
        ("café naïve", ["café", "naïve"]),
        ("lone / slash", ["lone", "slash"]),
    ],
)
def test_tokenize_keeps_words_dates_flags_and_paths(text: str, tokens: list[str]) -> None:
    assert search.tokenize(text) == tokens


def test_index_tokens_drop_stopwords_but_keep_negations() -> None:
    assert search.index_tokens("Where is the NAS, not the backup?") == ("na", "not", "backup")
    assert search.index_tokens("no, never, without, can't") == (
        "no",
        "never",
        "without",
        "can't",
    )


def test_query_terms_are_distinct_and_in_order() -> None:
    assert search.query_terms(["the", "nas", "restart", "nas", "order"]) == (
        "na",
        "restart",
        "order",
    )
    assert search.query_terms(["where", "are", "the", "backups"]) == ("backup",)
    assert search.query_terms(["the", "and"]) == ()


def test_query_terms_join_words_before_tokenizing() -> None:
    assert search.query_terms(["nas restart", "order"]) == ("na", "restart", "order")


def test_make_unit_collects_phrases_from_title_aliases_and_headings() -> None:
    unit = search.make_unit("The NAS", ["storage server"], ["Restart order"], ["Traefik first."])
    assert unit.title == ("na",)
    assert unit.aliases == ("storag", "server")
    assert unit.headings == ("restart", "order")
    assert unit.body == ("traefik", "first")
    assert unit.phrases == frozenset({"na", "storag server", "restart order"})


def test_make_unit_with_nothing_has_no_phrases() -> None:
    unit = search.make_unit("", [], [], [])
    assert unit.phrases == frozenset()
    assert unit.body == ()


def test_article_candidates_give_each_h2_and_a_top_with_prose() -> None:
    document = parse(
        "knowledge/a.md",
        "---\ntitle: Alpha\naliases:\n  - first\n---\n# Lead\n\nIntro words.\n\n"
        "## One\n\nBody one.\n\n### Sub\n\nSub body.\n\n## Two\n\nBody two.\n",
    )
    candidates = search.article_candidates(document)
    assert [(c.fragment, c.heading) for c in candidates] == [
        ("top", "Lead"),
        ("1", "One"),
        ("2", "Two"),
    ]
    one = candidates[1].unit
    assert one.headings == ("on", "sub")
    assert "bodi" in one.body
    assert "first" in one.aliases
    assert "alpha" in one.title


def test_top_without_prose_is_not_a_candidate() -> None:
    document = parse("knowledge/a.md", "# Only a heading\n\n## One\n\nText.\n")
    assert [c.fragment for c in search.article_candidates(document)] == ["1"]


def test_top_heading_falls_back_to_title_then_file_name() -> None:
    titled = parse("knowledge/t.md", "---\ntitle: Titled\n---\nProse here.\n")
    assert search.article_candidates(titled)[0].heading == "Titled"
    bare = parse("knowledge/bare.md", "Prose here.\n")
    assert search.article_candidates(bare)[0].heading == "bare"


def test_rank_qualifies_with_half_the_terms_rounded_up() -> None:
    units = [search.make_unit("", [], [], ["alpha beta"]), search.make_unit("", [], [], ["alpha"])]
    terms = ("alpha", "beta", "gamma")
    assert [hit.index for hit in search.rank(units, terms)] == [0]


def test_rank_requires_the_threshold_for_longer_queries() -> None:
    units = [
        search.make_unit("", [], [], ["alpha beta gamma"]),
        search.make_unit("", [], [], ["alpha"]),
    ]
    assert [hit.index for hit in search.rank(units, ("alpha", "beta", "gamma", "delta"))] == [0]
    assert search.rank(units, ("alpha", "beta", "delta", "eta", "zeta")) == []


def test_an_exact_phrase_qualifies_on_its_own() -> None:
    unit = search.make_unit("", [], ["Folder layout"], ["Unrelated words here."])
    assert [hit.index for hit in search.rank([unit], ("folder", "layout", "missing"))] == [0]


def test_title_and_heading_weights_outrank_body_matches() -> None:
    body_match = search.make_unit("", [], [], ["nas restart order"])
    heading_match = search.make_unit("", [], ["nas restart order"], [])
    ranked = [
        hit.index for hit in search.rank([body_match, heading_match], ("nas", "restart", "order"))
    ]
    assert ranked == [1, 0]


def test_a_rarer_term_scores_higher() -> None:
    units = [
        search.make_unit("", [], [], ["rare"]),
        search.make_unit("", [], [], ["common"]),
        search.make_unit("", [], [], ["common"]),
        search.make_unit("", [], [], ["common"]),
    ]
    hits = {hit.index: hit.score for hit in search.rank(units, ("rare", "common"))}
    assert hits[0] > hits[1]


def test_ties_keep_their_input_order() -> None:
    units = [search.make_unit("", [], [], ["alpha"]), search.make_unit("", [], [], ["alpha"])]
    assert [hit.index for hit in search.rank(units, ("alpha",))] == [0, 1]


def test_rank_with_no_terms_or_no_units_is_empty() -> None:
    unit = search.make_unit("", [], [], ["alpha"])
    assert search.rank([unit], ()) == []
    assert search.rank([], ("alpha",)) == []


def test_rank_with_only_empty_units_is_empty_and_does_not_divide_by_zero() -> None:
    assert search.rank([search.make_unit("", [], [], [])], ("alpha",)) == []


def test_clip_shortens_long_text_to_the_width_with_an_ellipsis() -> None:
    assert search.clip("short", 10) == "short"
    assert search.clip("exactly ten", 11) == "exactly ten"
    assert search.clip("a much longer title", 10) == "a much ..."


def test_excerpt_picks_the_line_with_the_most_distinct_terms() -> None:
    lines = ["alpha only", "alpha beta", "beta alpha", "nothing"]
    assert search.excerpt(lines, ["alpha", "beta"]) == "alpha beta"


def test_excerpt_of_a_short_line_is_the_whole_line() -> None:
    assert search.excerpt(["  Alpha beta.  "], ["beta"]) == "Alpha beta."


def test_excerpt_shortens_a_long_line_around_its_first_match() -> None:
    line = "x" * 100 + " needle here " + "y" * 100
    text = search.excerpt([line], search.query_terms(["needle"]))
    assert text.startswith("...")
    assert text.endswith("...")
    assert "needle" in text
    assert len(text) <= search.EXCERPT_WIDTH + 6


def test_excerpt_with_a_match_at_the_start_has_no_leading_ellipsis() -> None:
    line = "needle " + "y" * 200
    text = search.excerpt([line], search.query_terms(["needle"]))
    assert not text.startswith("...")
    assert text.endswith("...")


def test_excerpt_without_any_match_is_the_first_line_clipped() -> None:
    assert search.excerpt(["first line", "second"], ["zebra"]) == "first line"
    assert search.excerpt([], ["zebra"]) == ""


def test_evidence_unit_has_the_title_and_the_text_without_headings() -> None:
    document = parse(
        "observations/pending/a.md", "---\ntitle: Alpha note\n---\n### user\n\nBeta words.\n"
    )
    unit = search.evidence_unit(document)
    assert unit.title == ("alpha", "note")
    assert unit.headings == ()
    assert unit.body == ("beta", "word")


def test_a_flag_is_indexed_under_its_word_as_well_as_itself() -> None:
    assert search.index_tokens("run --rename now") == ("run", "--rename", "renam", "now")
    assert search.index_tokens("try --no-verify") == ("try", "--no-verify", "no", "verifi")


def test_a_query_keeps_a_flag_whole() -> None:
    assert search.query_terms(["--rename", "tracks"]) == ("--rename", "track")


def test_a_derived_noun_matches_its_base_verb() -> None:
    assert search.query_terms(["retention"]) == ("retain",)
    assert search.query_terms(["retained"]) == search.query_terms(["retention"])
    assert search.query_terms(["decision"]) == search.query_terms(["decide"])


def test_a_derived_form_indexes_under_the_base_verb() -> None:
    assert search.index_tokens("Current retention policy") == ("current", "retain", "polici")


def test_a_numeric_identifier_is_one_token() -> None:
    assert search.tokenize("dirs 50-59 and 50.10.") == ["dirs", "50-59", "and", "50.10"]


def test_words_joined_without_a_digit_tokenize_as_before() -> None:
    assert search.tokenize("well-known wikidata-pilot nas.md") == [
        "well",
        "known",
        "wikidata",
        "pilot",
        "nas",
        "md",
    ]


def test_a_date_stays_one_token() -> None:
    assert search.tokenize("on 2026-10-26") == ["on", "2026-10-26"]


def test_a_date_followed_by_a_dot_or_a_word_still_splits_as_before() -> None:
    assert search.tokenize("on 2026-10-26.md") == ["on", "2026-10-26", "md"]
    assert search.tokenize("2026-10-26-notes") == ["2026-10-26", "notes"]


def test_a_numeric_identifier_is_indexed_whole_and_by_part() -> None:
    assert search.index_tokens("Area 50-59") == ("area", "50-59", "50", "59")


def test_a_dotted_numeric_identifier_is_indexed_by_each_part() -> None:
    assert search.index_tokens("Python 3.14 and 192.168.1.10") == (
        "python",
        "3.14",
        "3",
        "14",
        "192.168.1.10",
        "192",
        "168",
        "1",
        "10",
    )


def test_a_numeric_identifier_drops_stopword_parts() -> None:
    assert search.index_tokens("2p42-a") == ("2p42-a", "2p42")


def test_a_flag_with_a_numeric_word_keeps_its_old_split() -> None:
    assert search.index_tokens("try --ipv4-only") == ("try", "--ipv4-only", "ipv4")


def test_a_query_keeps_a_numeric_identifier_whole() -> None:
    assert search.query_terms(["honeysuckle", "50-59"]) == ("honeysuckl", "50-59")


def test_a_query_of_separate_numbers_matches_their_parts() -> None:
    assert search.query_terms(["50", "59"]) == ("50", "59")


def test_a_numeric_identifier_qualifies_only_the_units_that_hold_it() -> None:
    units = [
        search.make_unit("", [], [], ["files under 50-59"]),
        search.make_unit("", [], [], ["50 apples and 59 pears"]),
    ]
    assert [hit.index for hit in search.rank(units, search.query_terms(["50-59"]))] == [0]
