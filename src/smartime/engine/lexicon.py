"""Read-only system lexicon backed by SQLite (built by tools/build_data.py).

Lookups are cached in memory because the decoder re-runs on every keystroke
and asks for the same readings over and over.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from . import bopomofo

# Highest code point; used to build "starts with" range queries on indexes.
_MAX_CHAR = "\U0010ffff"


class Lexicon:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        uri = self.path.resolve().as_uri() + "?mode=ro"
        self._con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._con.execute("PRAGMA query_only = 1")
        self.meta = dict(self._con.execute("SELECT key, value FROM meta"))

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
        self.max_phrase_syllables: int = int(max_len or 1)

        # Per-instance caches (lru_cache on bound methods would leak instances).
        self.phrases = lru_cache(maxsize=65536)(self._phrases)
        self.has_reading_prefix = lru_cache(maxsize=65536)(self._has_reading_prefix)
        self.en_score = lru_cache(maxsize=65536)(self._en_score)

    def close(self) -> None:
        self._con.close()

    # -- Chinese ---------------------------------------------------------
    def _phrases(self, reading: str) -> tuple[tuple[str, float], ...]:
        """All phrases for an exact reading, best first."""
        rows = self._con.execute(
            "SELECT phrase, max(score) AS s FROM zh WHERE reading = ? GROUP BY phrase ORDER BY s DESC",
            (reading,),
        ).fetchall()
        return tuple((p, s) for p, s in rows)

    def _has_reading_prefix(self, reading: str) -> bool:
        """True if some longer phrase starts with this syllable sequence."""
        lo = reading + "-"
        hi = reading + "."  # '.' sorts right after '-'
        row = self._con.execute(
            "SELECT 1 FROM zh WHERE reading >= ? AND reading < ? LIMIT 1", (lo, hi)
        ).fetchone()
        return row is not None

    def completions(self, prefix: str, limit: int = 8) -> list[tuple[str, str, float]]:
        """Phrases that start with ``prefix`` (text) and are longer than it."""
        rows = self._con.execute(
            "SELECT phrase, reading, max(score) AS s FROM zh "
            "WHERE phrase > ? AND phrase < ? GROUP BY phrase, reading ORDER BY s DESC LIMIT ?",
            (prefix, prefix + _MAX_CHAR, limit),
        ).fetchall()
        return [(p, r, s) for p, r, s in rows]

    # -- English ---------------------------------------------------------
    def _en_score(self, word: str) -> float | None:
        row = self._con.execute("SELECT score FROM en WHERE word = ?", (word,)).fetchone()
        return None if row is None else row[0]
