"""Hanyu Pinyin <-> bopomofo syllables, for the 拼音 input scheme.

The lexicon is keyed by bopomofo readings, so pinyin is only a different
spelling of the same syllables: ``wo`` = ㄨㄛ, ``zhuang`` = ㄓㄨㄤ. Every
toneless bopomofo syllable the lexicon knows gets its standard pinyin
spelling, and the table is inverted for typing.

Typing conventions (what common pinyin IMEs accept):

* tones are optional; a digit right after a syllable sets it:
  1 = 一聲 (no mark), 2 = ˊ, 3 = ˇ, 4 = ˋ, 5 = ˙ (neutral);
* ü is typed as ``v`` (lv 綠, nve 虐); after j/q/x/y it is plain ``u``
  (ju, xue, yun), and ``lue``/``nue`` are accepted too.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import bopomofo

INITIAL_PINYIN = {
    "ㄅ": "b", "ㄆ": "p", "ㄇ": "m", "ㄈ": "f", "ㄉ": "d", "ㄊ": "t", "ㄋ": "n", "ㄌ": "l",
    "ㄍ": "g", "ㄎ": "k", "ㄏ": "h", "ㄐ": "j", "ㄑ": "q", "ㄒ": "x",
    "ㄓ": "zh", "ㄔ": "ch", "ㄕ": "sh", "ㄖ": "r", "ㄗ": "z", "ㄘ": "c", "ㄙ": "s",
}
# Final (medial + rhyme) spelled after an initial.
_FINAL_AFTER_INITIAL = {
    "": "", "ㄚ": "a", "ㄛ": "o", "ㄜ": "e", "ㄝ": "e", "ㄞ": "ai", "ㄟ": "ei", "ㄠ": "ao", "ㄡ": "ou",
    "ㄢ": "an", "ㄣ": "en", "ㄤ": "ang", "ㄥ": "eng", "ㄦ": "er",
    "ㄧ": "i", "ㄧㄚ": "ia", "ㄧㄛ": "io", "ㄧㄝ": "ie", "ㄧㄞ": "iai", "ㄧㄠ": "iao", "ㄧㄡ": "iu",
    "ㄧㄢ": "ian", "ㄧㄣ": "in", "ㄧㄤ": "iang", "ㄧㄥ": "ing",
    "ㄨ": "u", "ㄨㄚ": "ua", "ㄨㄛ": "uo", "ㄨㄞ": "uai", "ㄨㄟ": "ui", "ㄨㄢ": "uan", "ㄨㄣ": "un",
    "ㄨㄤ": "uang", "ㄨㄥ": "ong",
    "ㄩ": "v", "ㄩㄝ": "ve", "ㄩㄢ": "van", "ㄩㄣ": "vn", "ㄩㄥ": "iong",
}
# Final with no initial (y/w spellings).
_FINAL_ALONE = {
    "ㄚ": "a", "ㄛ": "o", "ㄜ": "e", "ㄝ": "e", "ㄞ": "ai", "ㄟ": "ei", "ㄠ": "ao", "ㄡ": "ou",
    "ㄢ": "an", "ㄣ": "en", "ㄤ": "ang", "ㄥ": "eng", "ㄦ": "er",
    "ㄧ": "yi", "ㄧㄚ": "ya", "ㄧㄛ": "yo", "ㄧㄝ": "ye", "ㄧㄞ": "yai", "ㄧㄠ": "yao", "ㄧㄡ": "you",
    "ㄧㄢ": "yan", "ㄧㄣ": "yin", "ㄧㄤ": "yang", "ㄧㄥ": "ying",
    "ㄨ": "wu", "ㄨㄚ": "wa", "ㄨㄛ": "wo", "ㄨㄞ": "wai", "ㄨㄟ": "wei", "ㄨㄢ": "wan", "ㄨㄣ": "wen",
    "ㄨㄤ": "wang", "ㄨㄥ": "weng",
    "ㄩ": "yu", "ㄩㄝ": "yue", "ㄩㄢ": "yuan", "ㄩㄣ": "yun", "ㄩㄥ": "yong",
}
_SIBILANTS = set("ㄓㄔㄕㄖㄗㄘㄙ")  # zhi chi shi ri zi ci si: written with -i

TONE_DIGITS = {"1": "", "2": "ˊ", "3": "ˇ", "4": "ˋ", "5": "˙"}


def to_pinyin(plain: str) -> str | None:
    """Standard pinyin (ü as v) of a toneless bopomofo syllable, or None."""
    if not plain:
        return None
    initial = plain[0] if plain[0] in INITIAL_PINYIN else ""
    rest = plain[len(initial):]
    if not initial:
        return _FINAL_ALONE.get(rest)
    if not rest:
        return INITIAL_PINYIN[initial] + "i" if initial in _SIBILANTS else None
    if initial in "ㄐㄑㄒ" and rest.startswith("ㄩ"):
        fin = {"ㄩ": "u", "ㄩㄝ": "ue", "ㄩㄢ": "uan", "ㄩㄣ": "un", "ㄩㄥ": "iong"}.get(rest)
    elif initial in "ㄅㄆㄇㄈ" and rest == "ㄛ":
        fin = "o"  # bo po mo fo (not buo)
    else:
        fin = _FINAL_AFTER_INITIAL.get(rest)
    if fin is None:
        return None
    return INITIAL_PINYIN[initial] + fin


class PinyinTable:
    """Spelling -> toneless bopomofo syllables, for the syllables the
    lexicon actually has."""

    def __init__(self, plain_syllables: Iterable[str]):
        table: dict[str, set[str]] = {}
        for plain in plain_syllables:
            spelled = to_pinyin(plain)
            if spelled is None:
                continue
            for variant in _variants(spelled):
                table.setdefault(variant, set()).add(plain)
        self.syllables: dict[str, tuple[str, ...]] = {k: tuple(sorted(v)) for k, v in table.items()}
        self.prefixes = frozenset(s[:i] for s in self.syllables for i in range(1, len(s) + 1))
        self.max_len = max(map(len, self.syllables), default=0)

    def lookup(self, spelled: str) -> tuple[str, ...]:
        return self.syllables.get(spelled, ())


def _variants(spelled: str) -> set[str]:
    out = {spelled}
    if spelled in ("lve", "nve"):
        out.add(spelled.replace("v", "u"))  # lue / nue: no ㄌㄨㄝ to clash with
    return out


def spell(reading: str) -> str:
    """Keys that type a reading in pinyin (toneless): ㄨㄛˇ-ㄇㄣ˙ -> women."""
    return "".join(to_pinyin(bopomofo.strip_tone(s)) or "" for s in reading.split("-"))
