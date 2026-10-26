"""Tests for the Porter stemmer."""

import pytest

from kb import stem as stemmer


@pytest.mark.parametrize(
    ("word", "stem"),
    [
        ("caresses", "caress"),
        ("ponies", "poni"),
        ("ties", "ti"),
        ("caress", "caress"),
        ("cats", "cat"),
        ("feed", "feed"),
        ("agreed", "agre"),
        ("plastered", "plaster"),
        ("bled", "bled"),
        ("motoring", "motor"),
        ("sing", "sing"),
        ("conflated", "conflat"),
        ("troubled", "troubl"),
        ("sized", "size"),
        ("hopping", "hop"),
        ("tanned", "tan"),
        ("falling", "fall"),
        ("hissing", "hiss"),
        ("fizzed", "fizz"),
        ("failing", "fail"),
        ("filing", "file"),
        ("happy", "happi"),
        ("sky", "sky"),
        ("relational", "relat"),
        ("conditional", "condit"),
        ("rational", "ration"),
        ("valenci", "valenc"),
        ("hesitanci", "hesit"),
        ("digitizer", "digit"),
        ("conformabli", "conform"),
        ("radicalli", "radic"),
        ("differentli", "differ"),
        ("vileli", "vile"),
        ("analogousli", "analog"),
        ("predication", "predic"),
        ("operator", "oper"),
        ("feudalism", "feudal"),
        ("decisiveness", "decis"),
        ("hopefulness", "hope"),
        ("callousness", "callous"),
        ("formaliti", "formal"),
        ("sensitiviti", "sensit"),
        ("sensibiliti", "sensibl"),
        ("triplicate", "triplic"),
        ("formative", "form"),
        ("formalize", "formal"),
        ("electriciti", "electr"),
        ("electrical", "electr"),
        ("hopeful", "hope"),
        ("goodness", "good"),
        ("revival", "reviv"),
        ("allowance", "allow"),
        ("inference", "infer"),
        ("airliner", "airlin"),
        ("adjustable", "adjust"),
        ("defensible", "defens"),
        ("irritant", "irrit"),
        ("replacement", "replac"),
        ("adjustment", "adjust"),
        ("dependent", "depend"),
        ("adoption", "adopt"),
        ("communism", "commun"),
        ("activate", "activ"),
        ("angulariti", "angular"),
        ("effective", "effect"),
        ("bowdlerize", "bowdler"),
        ("probate", "probat"),
        ("rate", "rate"),
        ("cease", "ceas"),
        ("controll", "control"),
        ("roll", "roll"),
    ],
)
def test_porter_stems_the_published_examples(word: str, stem: str) -> None:
    assert stemmer.stem(word) == stem


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("configure", "configuration"),
        ("backups", "backup"),
        ("connecting", "connected"),
    ],
)
def test_related_forms_share_a_stem(first: str, second: str) -> None:
    assert stemmer.stem(first) == stemmer.stem(second)


@pytest.mark.parametrize("word", ["an", "is", "", "café", "2026", "don't", "x2"])
def test_short_or_non_letter_words_are_unchanged(word: str) -> None:
    assert stemmer.stem(word) == word
