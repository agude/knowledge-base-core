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
    assert search.index_tokens("Where is the NAS, not the backup?") == ("nas", "not", "backup")
    assert search.index_tokens("no, never, without, can't") == (
        "no",
        "never",
        "without",
        "can't",
    )


def test_query_terms_are_distinct_and_in_order() -> None:
    assert search.query_terms(["the", "nas", "restart", "nas", "order"]) == (
        "nas",
        "restart",
        "order",
    )
    assert search.query_terms(["where", "are", "the", "backups"]) == ("backups",)
    assert search.query_terms(["the", "and"]) == ()


def test_query_terms_join_words_before_tokenizing() -> None:
    assert search.query_terms(["nas restart", "order"]) == ("nas", "restart", "order")


def test_make_unit_collects_phrases_from_title_aliases_and_headings() -> None:
    unit = search.make_unit("The NAS", ["storage server"], ["Restart order"], ["Traefik first."])
    assert unit.title == ("nas",)
    assert unit.aliases == ("storage", "server")
    assert unit.headings == ("restart", "order")
    assert unit.body == ("traefik", "first")
    assert unit.phrases == frozenset({"nas", "storage server", "restart order"})


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
    assert one.headings == ("one", "sub")
    assert "body" in one.body
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
