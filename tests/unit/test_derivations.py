"""Tests for the derivation lexicon."""

from kb.derivations import BASE_FORMS
from kb.stem import stem


def test_every_entry_changes_the_stem() -> None:
    """An entry whose noun and verb share a stem changes no index term."""
    dead = {noun: verb for noun, verb in BASE_FORMS.items() if stem(noun) == stem(verb)}
    assert dead == {}


def test_merged_nouns_are_excluded() -> None:
    """A noun whose common meaning is unrelated to its verb is not mapped."""
    assert "application" not in BASE_FORMS
    assert "formation" not in BASE_FORMS
