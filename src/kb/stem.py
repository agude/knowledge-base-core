"""The Porter stemmer (Porter, 1980), so that related English word forms share a stem.

Only ASCII letter words are stemmed. Flags, paths, dates, and words with
other characters are returned as they are, so a stem never changes the
meaning of a command name or a path.
"""

import re

VOWELS = "aeiou"
STEP2 = (
    ("ational", "ate"),
    ("tional", "tion"),
    ("enci", "ence"),
    ("anci", "ance"),
    ("izer", "ize"),
    ("abli", "able"),
    ("alli", "al"),
    ("entli", "ent"),
    ("eli", "e"),
    ("ousli", "ous"),
    ("ization", "ize"),
    ("ation", "ate"),
    ("ator", "ate"),
    ("alism", "al"),
    ("iveness", "ive"),
    ("fulness", "ful"),
    ("ousness", "ous"),
    ("aliti", "al"),
    ("iviti", "ive"),
    ("biliti", "ble"),
)
STEP3 = (
    ("icate", "ic"),
    ("ative", ""),
    ("alize", "al"),
    ("iciti", "ic"),
    ("ical", "ic"),
    ("ful", ""),
    ("ness", ""),
)
STEP4 = (
    "al",
    "ance",
    "ence",
    "er",
    "ic",
    "able",
    "ible",
    "ant",
    "ement",
    "ment",
    "ent",
    "ion",
    "ou",
    "ism",
    "ate",
    "iti",
    "ous",
    "ive",
    "ize",
)


def stem(word: str) -> str:
    """The Porter stem of a word. Words shorter than three letters are unchanged."""
    if len(word) <= 2 or not (word.isascii() and word.isalpha()):
        return word
    word = _step1a(word)
    word = _step1b(word)
    word = _step1c(word)
    word = _replace(word, STEP2)
    word = _replace(word, STEP3)
    word = _step4(word)
    word = _step5a(word)
    return _step5b(word)


def _consonant(word: str, index: int) -> bool:
    char = word[index]
    if char in VOWELS:
        return False
    if char == "y":
        return index == 0 or not _consonant(word, index - 1)
    return True


def _measure(stem_text: str) -> int:
    """The number of vowel-consonant sequences in a stem, written [C](VC){m}[V]."""
    pattern = "".join(
        "c" if _consonant(stem_text, index) else "v" for index in range(len(stem_text))
    )
    return re.sub(r"(.)\1+", r"\1", pattern).count("vc")


def _has_vowel(stem_text: str) -> bool:
    return any(not _consonant(stem_text, index) for index in range(len(stem_text)))


def _double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _consonant(word, len(word) - 1)


def _cvc(word: str) -> bool:
    """True for consonant, vowel, consonant, where the last consonant is not w, x, or y."""
    if len(word) < 3:
        return False
    return (
        _consonant(word, len(word) - 3)
        and not _consonant(word, len(word) - 2)
        and _consonant(word, len(word) - 1)
        and word[-1] not in "wxy"
    )


def _step1a(word: str) -> str:
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def _step1b(word: str) -> str:
    if word.endswith("eed"):
        return word[:-1] if _measure(word[:-3]) > 0 else word
    for suffix in ("ed", "ing"):
        if word.endswith(suffix) and _has_vowel(word[: -len(suffix)]):
            return _tidy(word[: -len(suffix)])
    return word


def _tidy(word: str) -> str:
    """The repairs that follow a removed "ed" or "ing"."""
    if word.endswith(("at", "bl", "iz")):
        return word + "e"
    if _double_consonant(word) and word[-1] not in "lsz":
        return word[:-1]
    if _measure(word) == 1 and _cvc(word):
        return word + "e"
    return word


def _step1c(word: str) -> str:
    if word.endswith("y") and _has_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


def _replace(word: str, rules: tuple[tuple[str, str], ...]) -> str:
    """Apply the first rule whose suffix matches, if the stem left is long enough."""
    for suffix, replacement in rules:
        if word.endswith(suffix):
            stem_text = word[: -len(suffix)]
            return stem_text + replacement if _measure(stem_text) > 0 else word
    return word


def _step4(word: str) -> str:
    for suffix in STEP4:
        if word.endswith(suffix):
            stem_text = word[: -len(suffix)]
            if suffix == "ion":
                return (
                    stem_text if _measure(stem_text) > 1 and stem_text[-1:] in ("s", "t") else word
                )
            return stem_text if _measure(stem_text) > 1 else word
    return word


def _step5a(word: str) -> str:
    if word.endswith("e"):
        stem_text = word[:-1]
        measure = _measure(stem_text)
        if measure > 1 or (measure == 1 and not _cvc(stem_text)):
            return stem_text
    return word


def _step5b(word: str) -> str:
    if _measure(word) > 1 and _double_consonant(word) and word.endswith("l"):
        return word[:-1]
    return word
