"""Keyboard layouts: physical key character <-> bopomofo symbol."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import bopomofo


@dataclass(frozen=True)
class Layout:
    name: str
    display_name: str
    symbols: dict[str, str]  # key char -> non-tone bopomofo symbol
    tones: dict[str, str]  # key char -> tone mark ('' = tone 1)
    _symbol_keys: dict[str, str] = field(init=False, repr=False)
    _tone_keys: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_symbol_keys", {v: k for k, v in self.symbols.items()})
        object.__setattr__(self, "_tone_keys", {v: k for k, v in self.tones.items()})

    def symbol(self, key: str) -> str | None:
        return self.symbols.get(key)

    def tone(self, key: str) -> str | None:
        return self.tones.get(key)

    def is_layout_key(self, key: str) -> bool:
        return key in self.symbols or key in self.tones

    def keys_for_syllable(self, syllable: str) -> str:
        tone = bopomofo.tone_of(syllable)
        body = bopomofo.strip_tone(syllable)
        return "".join(self._symbol_keys[s] for s in body) + self._tone_keys[tone]

    def keys_for_reading(self, reading: str) -> str:
        """``ㄨㄛˇ-ㄇㄣ˙`` -> ``ji3ap7``."""
        return "".join(self.keys_for_syllable(s) for s in reading.split("-"))

    def symbols_for_keys(self, keys: str) -> str:
        """Best-effort display of raw keys as bopomofo (used for the hint)."""
        out = []
        for k in keys:
            s = self.symbols.get(k)
            if s is None:
                t = self.tones.get(k)
                if t is None:
                    return ""
                s = t
            out.append(s)
        return "".join(out)


# 大千 (standard) layout — the default layout of Windows / most zhuyin IMEs.
DACHEN = Layout(
    name="dachen",
    display_name="大千（標準）",
    symbols={
        "1": "ㄅ", "q": "ㄆ", "a": "ㄇ", "z": "ㄈ",
        "2": "ㄉ", "w": "ㄊ", "s": "ㄋ", "x": "ㄌ",
        "e": "ㄍ", "d": "ㄎ", "c": "ㄏ",
        "r": "ㄐ", "f": "ㄑ", "v": "ㄒ",
        "5": "ㄓ", "t": "ㄔ", "g": "ㄕ", "b": "ㄖ",
        "y": "ㄗ", "h": "ㄘ", "n": "ㄙ",
        "u": "ㄧ", "j": "ㄨ", "m": "ㄩ",
        "8": "ㄚ", "i": "ㄛ", "k": "ㄜ", ",": "ㄝ",
        "9": "ㄞ", "o": "ㄟ", "l": "ㄠ", ".": "ㄡ",
        "0": "ㄢ", "p": "ㄣ", ";": "ㄤ", "/": "ㄥ",
        "-": "ㄦ",
    },
    tones={" ": "", "6": "ˊ", "3": "ˇ", "4": "ˋ", "7": "˙"},
)

LAYOUTS = {DACHEN.name: DACHEN}


def get_layout(name: str) -> Layout:
    return LAYOUTS.get(name, DACHEN)
