"""Lexicon = read-only system dictionary (SQLite, built by tools/build_data.py)
plus, optionally, the user's own dictionary and learned memory (UserDict).

Lookups are cached in memory because the decoder re-runs on every keystroke
and asks for the same readings over and over. ``refresh()`` drops the caches
when the user dictionary changed (learning, or edits in the settings app).
"""

from __future__ import annotations

import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from . import bopomofo
from .pinyin import PinyinTable
from .userdict import Entry, UserDict

_TONES = str.maketrans("", "", bopomofo.TONE_MARKS)


def plain(reading: str) -> str:
    """Reading without tone marks: ㄨㄛˇ-ㄇㄣ˙ -> ㄨㄛ-ㄇㄣ (pinyin is typed toneless)."""
    return reading.translate(_TONES)

# Highest code point; used to build "starts with" range queries on indexes.
_MAX_CHAR = "\U0010ffff"


def abbr_key(reading: str) -> str:
    """ㄨㄛˇ-ㄇㄣ˙ -> ㄨㄇ (the first symbol of each syllable)."""
    return "".join((bopomofo.components(s) or [s[:1]])[0] for s in reading.split("-"))


class Lexicon:
    def __init__(self, db_path: str | Path, user: UserDict | None = None):
        self.path = Path(db_path)
        uri = self.path.resolve().as_uri() + "?mode=ro"
        self._con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._con.execute("PRAGMA query_only = 1")
        self.meta = dict(self._con.execute("SELECT key, value FROM meta"))
        self.user = user

        singles = [r for (r,) in self._con.execute("SELECT DISTINCT reading FROM zh WHERE instr(reading, '-') = 0")]
        self.valid_syllables: frozenset[str] = frozenset(singles)
        partials: set[str] = set()
        for syl in singles:
            comps = bopomofo.components(syl)
            # every non-empty subset, kept in canonical order (bitmask over <= 3 slots)
            for mask in range(1, 1 << len(comps)):
                partials.add("".join(c for i, c in enumerate(comps) if mask >> i & 1))
        # Canonical-order pieces of real syllables, e.g. ㄒ, ㄩ, ㄒㄩ, ㄒㄣ, ㄒㄩㄣ.
        # A pending (tone not yet typed) key group is plausible if its
        # canonical form is in this set, whatever order it was typed in.
        self.partial_syllables: frozenset[str] = frozenset(partials)
        (max_len,) = self._con.execute(
            "SELECT max(length(reading) - length(replace(reading, '-', '')) + 1) FROM zh"
        ).fetchone()
        self._system_max_syllables = int(max_len or 1)
        columns = {row[1] for row in self._con.execute("PRAGMA table_info(zh)")}
        tables = {n for (n,) in self._con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # schema 2 (tools/build_data.py): toneless readings and Cangjie codes
        self.has_pinyin = "plain" in columns
        self.has_cangjie = "cangjie" in tables
        self._pinyin: PinyinTable | None = None
        self._abbr: dict[str, list[tuple[str, str]]] | None = None  # 瘋狂模式, built on first use
        self._abbr_lock = threading.Lock()
        self._make_caches()

    def _make_caches(self) -> None:
        # Per-instance caches (lru_cache on bound methods would leak instances).
        self.phrases = lru_cache(maxsize=65536)(self._phrases)
        self.has_reading_prefix = lru_cache(maxsize=65536)(self._has_reading_prefix)
        self.en_score = lru_cache(maxsize=65536)(self._en_score)
        self.system_phrases = lru_cache(maxsize=65536)(self._system_phrases)
        self.plain_phrases = lru_cache(maxsize=65536)(self._plain_phrases)
        self.has_plain_prefix = lru_cache(maxsize=65536)(self._has_plain_prefix)
        self.cangjie_chars = lru_cache(maxsize=16384)(self._cangjie_chars)
        self.cangjie_code = lru_cache(maxsize=16384)(self._cangjie_code)
        self.text_info = lru_cache(maxsize=65536)(self._text_info)
        self.abbreviations = lru_cache(maxsize=16384)(self._abbreviations)
        self.max_phrase_syllables = max(self._system_max_syllables, self.user.max_syllables if self.user else 0)
        # my own phrases by toneless reading and by text (pinyin, Cangjie)
        self._user_plain: dict[str, list[str]] = {}
        self._user_text: dict[str, list[str]] = {}
        self._user_abbr: dict[str, list[tuple[str, str]]] = {}
        if self.user is not None:
            for reading, by_phrase in self.user.zh.items():
                self._user_plain.setdefault(plain(reading), []).append(reading)
                for phrase in by_phrase:
                    self._user_text.setdefault(phrase, []).append(reading)
                    self._user_abbr.setdefault(abbr_key(reading), []).append((phrase, reading))

    def refresh(self) -> bool:
        """Call before decoding; cheap. True if the user dictionary changed."""
        if self.user is not None and self.user.refresh():
            self.invalidate()
            return True
        return False

    def invalidate(self) -> None:
        """Drop caches after this process changed the user dictionary."""
        self._make_caches()

    def close(self) -> None:
        self._con.close()

    # -- 瘋狂模式 (abbreviated zhuyin) ------------------------------------
    def _build_abbr(self) -> dict[str, list[tuple[str, str]]]:
        """Common phrases by the first symbol of each syllable (我們 -> ㄨㄇ),
        the best 24 per key. About half a second, once."""
        index: dict[str, list[tuple[float, str, str]]] = {}
        for reading, phrase, score in self._con.execute(
                "SELECT reading, phrase, max(score) FROM zh WHERE score > -7 GROUP BY reading, phrase"):
            index.setdefault(abbr_key(reading), []).append((score, phrase, reading))
        return {k: [(p, r) for _, p, r in sorted(v, reverse=True)[:24]] for k, v in index.items()}

    def _abbr_index(self) -> dict[str, list[tuple[str, str]]]:
        if self._abbr is None:
            with self._abbr_lock:
                if self._abbr is None:
                    self._abbr = self._build_abbr()
        return self._abbr

    def warm_abbreviations(self) -> None:
        """Build the 瘋狂模式 index in the background. Built on the first key
        instead, that key stalled for about a third of a second — the one
        measurable part of 「打開以後速度感覺變超級慢」 (every key after it
        takes 0–2 ms)."""
        if self._abbr is None:
            threading.Thread(target=self._abbr_index, name="abbr-index", daemon=True).start()

    def _abbreviations(self, key: str) -> tuple[tuple[str, str, float], ...]:
        """Phrases whose syllables start with these symbols (one symbol per
        syllable), best first, my memory applied: ㄨㄇ -> 我們 …"""
        index = self._abbr_index()
        out: dict[tuple[str, str], float] = {}
        for phrase, reading in index.get(key, []) + self._user_abbr.get(key, []):
            for p, s in self.phrases(reading):
                if p == phrase:
                    out[(p, reading)] = s
                    break
        return tuple(sorted(((p, r, s) for (p, r), s in out.items()), key=lambda t: -t[2]))

    # -- Chinese ---------------------------------------------------------
    def _system_phrases(self, reading: str) -> tuple[tuple[str, float], ...]:
        rows = self._con.execute(
            "SELECT phrase, max(score) AS s FROM zh WHERE reading = ? GROUP BY phrase ORDER BY s DESC",
            (reading,),
        ).fetchall()
        return tuple((p, s) for p, s in rows)

    def _phrases(self, reading: str) -> tuple[tuple[str, float], ...]:
        """All phrases for an exact reading, best first (user memory applied)."""
        system = self.system_phrases(reading)
        user = self.user
        if user is None:
            return system
        mine = user.zh.get(reading, {})
        out: dict[str, float] = {}
        for p, s in system:
            if user.is_blocked(p, reading):
                continue
            e = mine.get(p)
            out[p] = e.score(s) if e else s
        for p, e in mine.items():
            if p not in out and not user.is_blocked(p, reading):
                out[p] = e.score(None)
        return tuple(sorted(out.items(), key=lambda kv: -kv[1]))

    def entry(self, phrase: str, reading: str) -> Entry | None:
        return self.user.lookup(phrase, reading) if self.user else None

    def in_system(self, phrase: str, reading: str) -> bool:
        return any(p == phrase for p, _ in self.system_phrases(reading))

    def _has_reading_prefix(self, reading: str) -> bool:
        """True if some longer phrase starts with this syllable sequence."""
        if self.user is not None and reading in self.user.prefixes:
            return True
        lo = reading + "-"
        hi = reading + "."  # '.' sorts right after '-'
        row = self._con.execute(
            "SELECT 1 FROM zh WHERE reading >= ? AND reading < ? LIMIT 1", (lo, hi)
        ).fetchone()
        return row is not None

    # -- Pinyin (toneless readings) -------------------------------------
    @property
    def pinyin(self) -> PinyinTable:
        if self._pinyin is None:
            self._pinyin = PinyinTable(plain(s) for s in self.valid_syllables)
        return self._pinyin

    def _scored(self, phrase: str, reading: str, system: float | None) -> float | None:
        """A phrase's score with my memory applied; None if blocked."""
        user = self.user
        if user is None:
            return system
        if user.is_blocked(phrase, reading):
            return None
        e = user.lookup(phrase, reading)
        if e is not None:
            return e.score(system)
        return system

    def _plain_phrases(self, plain_reading: str) -> tuple[tuple[str, str, float], ...]:
        """(phrase, reading, score) for a toneless reading, best first."""
        if not self.has_pinyin:
            return ()
        rows = self._con.execute(
            "SELECT phrase, reading, max(score) AS s FROM zh WHERE plain = ? GROUP BY phrase, reading",
            (plain_reading,),
        ).fetchall()
        out: dict[tuple[str, str], float] = {}
        for p, r, s in rows:
            sc = self._scored(p, r, s)
            if sc is not None:
                out[(p, r)] = sc
        for r in self._user_plain.get(plain_reading, ()):
            for p, e in self.user.zh.get(r, {}).items():
                if (p, r) not in out and not self.user.is_blocked(p, r):
                    out[(p, r)] = e.score(None)
        return tuple((p, r, sc) for (p, r), sc in sorted(out.items(), key=lambda kv: -kv[1]))

    def _has_plain_prefix(self, plain_reading: str) -> bool:
        if not self.has_pinyin:
            return False
        if any(k.startswith(plain_reading + "-") for k in self._user_plain):
            return True
        row = self._con.execute(
            "SELECT 1 FROM zh WHERE plain >= ? AND plain < ? LIMIT 1", (plain_reading + "-", plain_reading + ".")
        ).fetchone()
        return row is not None

    # -- Cangjie ----------------------------------------------------------
    def _cangjie_chars(self, code: str) -> tuple[str, ...]:
        """Characters with this Cangjie 5 code, most common first."""
        if not self.has_cangjie:
            return ()
        return tuple(c for (c,) in self._con.execute("SELECT char FROM cangjie WHERE code = ? ORDER BY rank", (code,)))

    def _cangjie_code(self, char: str) -> str:
        """The (shortest) Cangjie code of a character, "" if unknown."""
        if not self.has_cangjie:
            return ""
        row = self._con.execute(
            "SELECT code FROM cangjie WHERE char = ? ORDER BY length(code), rank LIMIT 1", (char,)).fetchone()
        return row[0] if row else ""

    def _text_info(self, text: str) -> tuple[str, float] | None:
        """Best (reading, score) of a phrase given as text (Cangjie types
        characters, not readings), with my memory applied."""
        rows = self._con.execute(
            "SELECT reading, max(score) FROM zh WHERE phrase = ? GROUP BY reading", (text,)).fetchall()
        best: tuple[str, float] | None = None
        for r, s in rows:
            sc = self._scored(text, r, s)
            if sc is not None and (best is None or sc > best[1]):
                best = (r, sc)
        for r in self._user_text.get(text, ()):
            e = self.user.lookup(text, r)
            if e is not None and not e.blocked and (best is None or e.score(None) > best[1]):
                if not any(r == x for x, _ in rows):
                    best = (r, e.score(None))
        return best

    def completions(self, prefix: str, limit: int = 8) -> list[tuple[str, str, float]]:
        """Phrases that start with ``prefix`` (text) and are longer than it,
        best first. Learned and added phrases count, blocked ones are skipped."""
        rows = self._con.execute(
            "SELECT phrase, reading, max(score) AS s FROM zh "
            "WHERE phrase > ? AND phrase < ? GROUP BY phrase, reading ORDER BY s DESC LIMIT ?",
            (prefix, prefix + _MAX_CHAR, limit * 2),
        ).fetchall()
        user = self.user
        out: dict[tuple[str, str], float] = {}
        for p, r, s in rows:
            if user is not None:
                if user.is_blocked(p, r):
                    continue
                e = user.lookup(p, r)
                if e is not None:
                    s = e.score(s)
            out[(p, r)] = s
        if user is not None:
            for r, by_phrase in user.zh.items():
                for p, e in by_phrase.items():
                    if p.startswith(prefix) and len(p) > len(prefix) and (p, r) not in out:
                        out[(p, r)] = e.score(None)
        ranked = sorted(out.items(), key=lambda kv: -kv[1])[:limit]
        return [(p, r, s) for (p, r), s in ranked]

    def reading_for(self, text: str) -> str | None:
        """Most likely reading of a Chinese string (for adding a word in
        Settings without typing its zhuyin). Whole phrase first, then char
        by char with each character's most common reading."""
        row = self._con.execute(
            "SELECT reading FROM zh WHERE phrase = ? ORDER BY score DESC LIMIT 1", (text,)
        ).fetchone()
        if row:
            return row[0]
        syllables = []
        for ch in text:
            row = self._con.execute(
                "SELECT reading FROM zh WHERE phrase = ? AND instr(reading, '-') = 0 ORDER BY score DESC LIMIT 1",
                (ch,),
            ).fetchone()
            if row is None:
                return None
            syllables.append(row[0])
        return "-".join(syllables)

    def readings_of_char(self, ch: str) -> list[str]:
        """All readings of one character, most common first (多音字)."""
        return [r for (r,) in self._con.execute(
            "SELECT reading FROM zh WHERE phrase = ? AND instr(reading, '-') = 0 ORDER BY score DESC", (ch,)
        )]

    # -- English ---------------------------------------------------------
    def _en_score(self, word: str) -> float | None:
        row = self._con.execute("SELECT score FROM en WHERE word = ?", (word,)).fetchone()
        system = None if row is None else row[0]
        if self.user is not None:
            if self.user.is_blocked(word, ""):
                return None  # "never as English": scored like an unknown token
            e = self.user.en.get(word)
            if e is not None:
                return e.score(system)
        return system
