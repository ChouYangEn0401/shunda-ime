"""Clean up recognized text and build recognition hints from my dictionary."""

from __future__ import annotations

import re
from collections.abc import Iterable

_CJK = "　-鿿＀-￯"
_SPACES_AROUND_CJK = re.compile(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])")
_HAS_CJK = re.compile(rf"[{_CJK}]")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
# "MV P", "A P I": an acronym SenseVoice split into pieces
_SPLIT_CAPS = re.compile(r"(?<![A-Za-z'’])[A-Z]{1,3}(?: [A-Z]{1,3})+(?![A-Za-z'’])")
# short words that are ordinary English, not acronyms (kept lowercase)
_SHORT_WORDS = frozenset("""
A AM AN AS AT BE BY DO GO HE IF IN IS IT ME MY NO OF OH ON OR SO TO UP US WE
THE AND FOR YOU ARE WAS BUT NOT CAN ALL ONE TWO GET GOT HAS HAD HOW WHO WHY YES
HIM HER HIS OUR SHE ITS NEW NOW OUT SEE USE WAY DAY MAN OFF OLD TOO ANY SAY LET
PUT TRY BIG END ASK OWN FEW LOT SET RUN BOY GOD SIR BYE HEY HI
""".split())
_converter = None


def to_traditional(text: str) -> str:
    """Taiwan Traditional characters (OpenCC s2tw). Only characters change,
    not vocabulary: s2twp would turn the 文件 someone said into 檔案.
    Harmless on text that is already Traditional."""
    global _converter
    if _converter is None:
        from opencc import OpenCC

        _converter = OpenCC("s2tw")
    return _converter.convert(text)


def fix_english(text: str, known: Iterable[str] = ()) -> str:
    """SenseVoice writes English in capitals and sometimes splits acronyms
    ("MEETING", "MV P"); my dictionary's spelling wins ("vscode" -> VSCode)."""
    spelling = {w.replace(" ", "").upper(): w for w in known if w and w.isascii() and _WORD.search(w)}
    for w in sorted(spelling.values(), key=len, reverse=True):
        # my word in any case, even split into pieces ("V S CODE")
        pattern = " ?".join(re.escape(c) for c in w if not c.isspace())
        text = re.sub(rf"(?<![A-Za-z]){pattern}(?![A-Za-z])", lambda m, w=w: w, text, flags=re.IGNORECASE)

    def join(m: re.Match) -> str:
        parts = m.group(0).split(" ")
        joined = "".join(parts)
        if joined in spelling:
            return spelling[joined]
        if len(parts) == 2 and len(joined) <= 4 and min(map(len, parts)) == 1 \
                and not any(p in _SHORT_WORDS or p == "I" for p in parts):
            return joined
        return m.group(0)

    text = _SPLIT_CAPS.sub(join, text)
    letters = [c for c in text if c.isascii() and c.isalpha()]
    all_caps = len(letters) >= 4 and not any(c.islower() for c in letters)

    def word(m: re.Match) -> str:
        w = m.group(0)
        if w.upper() in spelling:
            return spelling[w.upper()]
        if not all_caps or w == "I":
            return w
        if len(w) <= 3 and w.isalpha() and w not in _SHORT_WORDS:
            return w  # API, MVP, UI: an acronym
        w = w.lower()
        return "I" + w[1:] if w[:2] in ("i'", "i’") else w  # I'M -> I'm

    text = _WORD.sub(word, text)
    if all_caps and not _HAS_CJK.search(text):
        text = text[:1].upper() + text[1:]  # an English sentence
    return text


def clean(text: str, traditional: bool = True, known: Iterable[str] = ()) -> str:
    text = text.strip()
    if traditional:
        text = to_traditional(text)
    text = _SPACES_AROUND_CJK.sub("", text)  # 我 要 去 -> 我要去
    text = fix_english(text, known)
    text = text.replace("\n", " ")
    return text


def my_words(user, limit: int = 60) -> list[str]:
    """My own words (friends' names, project terms, English terms), most
    used first: hints for the recognizer and the spelling of English terms."""
    if user is None:
        return []
    words = [e["phrase"] for e in user.list(source="manual", blocked=False, limit=limit)]
    return list(dict.fromkeys(w for w in words if w))


def hotwords_from_dictionary(user, limit: int = 60) -> str:
    return " ".join(my_words(user, limit))
