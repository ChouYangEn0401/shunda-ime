"""Bopomofo (注音) syllable structure.

A Mandarin syllable written in bopomofo has at most one symbol from each
category, always in this order:

    initial (聲母) -> medial (介音) -> final (韻母) -> tone (聲調)

Tone 1 is written without a mark (the space key in the 大千 layout); the
neutral tone mark ˙ is written as a suffix, matching McBopomofo's data.
"""

from __future__ import annotations

from collections.abc import Iterable

INITIALS = "ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ"
MEDIALS = "ㄧㄨㄩ"
FINALS = "ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ"
TONE_MARKS = "ˊˇˋ˙"

INITIAL, MEDIAL, FINAL, TONE = range(4)

_CATEGORY: dict[str, int] = {}
for _cat, _syms in ((INITIAL, INITIALS), (MEDIAL, MEDIALS), (FINAL, FINALS), (TONE, TONE_MARKS)):
    for _s in _syms:
        _CATEGORY[_s] = _cat


def category(symbol: str) -> int | None:
    """Return INITIAL/MEDIAL/FINAL/TONE for a bopomofo symbol, else None."""
    return _CATEGORY.get(symbol)


def is_symbol(ch: str) -> bool:
    return ch in _CATEGORY and _CATEGORY[ch] != TONE


def compose_strict(symbols: Iterable[str], tone: str = "") -> str | None:
    """Join symbols into a syllable only if they are already in canonical order.

    This is the behaviour of a classic zhuyin IME: ``ㄨㄛ`` + ˇ is accepted,
    ``ㄛㄨ`` + ˇ is rejected. Returns None when the order or the categories
    are invalid. Whether the result is a *real* syllable is checked against
    the lexicon separately.
    """
    last = -1
    out = []
    for s in symbols:
        cat = _CATEGORY.get(s)
        if cat is None or cat == TONE or cat <= last:
            return None
        last = cat
        out.append(s)
    if not out:
        return None
    if tone and _CATEGORY.get(tone) != TONE:
        return None
    return "".join(out) + tone


def strip_tone(syllable: str) -> str:
    if syllable and syllable[-1] in TONE_MARKS:
        return syllable[:-1]
    return syllable


def tone_of(syllable: str) -> str:
    """Return the tone mark ('' for tone 1)."""
    if syllable and syllable[-1] in TONE_MARKS:
        return syllable[-1]
    return ""
