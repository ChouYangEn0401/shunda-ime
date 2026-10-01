"""Lexicon = read-only system dictionary (SQLite, built by tools/build_data.py)
plus, optionally, the user's own dictionary and learned memory (UserDict).

Lookups are cached in memory because the decoder re-runs on every keystroke
and asks for the same readings over and over. ``refresh()`` drops the caches
when the user dictionary changed (learning, or edits in the settings app).
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from . import bopomofo
from .userdict import Entry, UserDict

# Highest code point; used to build "starts with" range queries on indexes.
_MAX_CHAR = "\U0010ffff"


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
        self._make_caches()

    def _make_caches(self) -> None:
        # Per-instance caches (lru_cache on bound methods would leak instances).
        self.phrases = lru_cache(maxsize=65536)(self._phrases)
        self.has_reading_prefix = lru_cache(maxsize=65536)(self._has_reading_prefix)
        self.en_score = lru_cache(maxsize=65536)(self._en_score)
        self.system_phrases = lru_cache(maxsize=65536)(self._system_phrases)
        self.max_phrase_syllables = max(self._system_max_syllables, self.user.max_syllables if self.user else 0)

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
