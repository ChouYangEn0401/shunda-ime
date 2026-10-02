"""The user's own dictionary and learned memory (%APPDATA%\\SmartIME\\user.db).

What is stored
  * entries the user added (朋友名字, 專案術語 …) with a category: 我的詞庫
  * phrases learned from explicit choices, not yet sorted by the user: the
    自動收集 inbox of the settings page. ``origin`` says how: a candidate
    picked (pick), a character corrected inside a sentence — remembered
    together with its neighbour as a word, so the same context comes out
    right next time (fix), a Tab continuation accepted (tab). Text the
    decoder guessed and the user left alone is *not* learned, so a wrong
    guess cannot teach itself (the complaint about Windows' IME). Giving an
    inbox entry a category moves it to 我的詞庫.
  * blocked phrases: "never suggest this" (Delete key in the candidate window)

Everything is per user and local. The settings app writes to the same
SQLite file; the IME notices through ``PRAGMA data_version`` and reloads.
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 2  # 2: entries.origin
ORIGINS = ("pick", "fix", "tab")
DEFAULT_CATEGORIES = ("常用詞", "朋友", "專案術語", "常用英文")

# Learned words used only once and not again for this long are forgotten
# (tidy): one-off picks should not pile up forever. Words the user added and
# "never suggest" blocks are always kept.
TIDY_AFTER_DAYS = 120

# Scores are log10 like the system lexicon (common words ≈ -3, rare ≈ -7).
MANUAL_BASE = -3.0  # an added word is at least as likely as a common word
LEARNED_NEW_BASE = -6.0  # a learned word the system lexicon does not know


def boost(count: int) -> float:
    """Extra log10 score from usage: 1 use ≈ +0.9, 4 ≈ +2.1, capped at +3."""
    if count <= 0:
        return 0.0
    return min(3.0, 0.9 + 0.6 * math.log2(count))


@dataclass
class Entry:
    id: int
    phrase: str
    reading: str  # "ㄨㄛˇ-ㄇㄣ˙" for Chinese, "" for English
    kind: str  # "zh" | "en"
    category: str | None
    source: str  # "manual" | "learned"
    count: int
    last_used: float | None
    blocked: bool
    origin: str = ""  # learned entries: pick | fix | tab
    created: float | None = None

    def score(self, system: float | None) -> float:
        if self.source == "manual":
            base = MANUAL_BASE if system is None else max(system, MANUAL_BASE)
        else:
            base = LEARNED_NEW_BASE if system is None else system
        return base + boost(self.count)


class UserDict:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=5)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self.version = 0  # bumped on every reload; caches key on it
        self._data_version = None
        self._load()

    # ------------------------------------------------------------ schema
    def _init_schema(self) -> None:
        c = self._con
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, sort INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY,
                phrase TEXT NOT NULL,
                reading TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'zh',
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                source TEXT NOT NULL DEFAULT 'learned',
                count INTEGER NOT NULL DEFAULT 0,
                last_used REAL,
                created REAL NOT NULL,
                blocked INTEGER NOT NULL DEFAULT 0,
                UNIQUE (phrase, reading));
            CREATE INDEX IF NOT EXISTS entries_reading ON entries(reading);
            """
        )
        if c.execute("SELECT value FROM meta WHERE key='schema'").fetchone() is None:
            c.execute("INSERT INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
            for i, name in enumerate(DEFAULT_CATEGORIES):
                c.execute("INSERT OR IGNORE INTO categories (name, sort) VALUES (?, ?)", (name, i))
        columns = {r[1] for r in c.execute("PRAGMA table_info(entries)")}
        if "origin" not in columns:  # schema 1 -> 2
            c.execute("ALTER TABLE entries ADD COLUMN origin TEXT NOT NULL DEFAULT ''")
            c.execute("UPDATE meta SET value=? WHERE key='schema'", (str(SCHEMA_VERSION),))

    # ------------------------------------------------------------ cache
    def _load(self) -> None:
        self.zh: dict[str, dict[str, Entry]] = {}  # reading -> phrase -> entry
        self.en: dict[str, Entry] = {}  # lowercase word -> entry
        self.blocked: set[tuple[str, str]] = set()
        prefixes: set[str] = set()
        max_syl = 0
        for e in self._entries():
            if e.blocked:
                self.blocked.add((e.phrase, e.reading))
                continue
            if e.kind == "en":
                self.en[e.phrase.lower()] = e
                continue
            self.zh.setdefault(e.reading, {})[e.phrase] = e
            syl = e.reading.split("-")
            max_syl = max(max_syl, len(syl))
            for i in range(1, len(syl)):
                prefixes.add("-".join(syl[:i]))
        self.prefixes = frozenset(prefixes)
        self.max_syllables = max_syl
        self._data_version = self._con.execute("PRAGMA data_version").fetchone()[0]
        self.version += 1

    def refresh(self) -> bool:
        """Reload if another process (the settings app) changed the file."""
        dv = self._con.execute("PRAGMA data_version").fetchone()[0]
        if dv != self._data_version:
            self._load()
            return True
        return False

    def _entries(self, where: str = "", args: tuple = ()) -> list[Entry]:
        rows = self._con.execute(
            "SELECT e.id, e.phrase, e.reading, e.kind, c.name, e.source, e.count, e.last_used, e.blocked, "
            "e.origin, e.created FROM entries e LEFT JOIN categories c ON c.id = e.category_id " + where, args
        ).fetchall()
        return [Entry(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], bool(r[8]), r[9], r[10]) for r in rows]

    # ------------------------------------------------------------ lookups (engine)
    def lookup(self, phrase: str, reading: str) -> Entry | None:
        if (phrase, reading) in self.blocked:
            return None
        if reading == "":
            return self.en.get(phrase.lower())
        return self.zh.get(reading, {}).get(phrase)

    def is_blocked(self, phrase: str, reading: str) -> bool:
        return (phrase, reading) in self.blocked

    # ------------------------------------------------------------ writes (engine)
    def learn(self, phrase: str, reading: str = "", kind: str = "zh", origin: str = "pick") -> bool:
        """Count one explicit use. True when the phrase was not in my memory
        before (the IME tells the user once). ``origin``: pick | fix | tab;
        a correction (fix) is the strongest signal and is kept as the origin."""
        now = time.time()
        known = self._con.execute(
            "SELECT 1 FROM entries WHERE phrase=? AND reading=?", (phrase, reading)).fetchone() is not None
        self._con.execute(
            "INSERT INTO entries (phrase, reading, kind, source, count, last_used, created, origin) "
            "VALUES (?, ?, ?, 'learned', 1, ?, ?, ?) "
            "ON CONFLICT (phrase, reading) DO UPDATE SET count = count + 1, last_used = excluded.last_used, "
            "origin = CASE WHEN origin = 'fix' THEN origin ELSE excluded.origin END",
            (phrase, reading, kind, now, now, origin),
        )
        self._load()
        return not known

    def forget(self, phrase: str, reading: str, kind: str = "zh") -> str:
        """Delete key on a candidate. Returns what happened:
        "manual"  - the user's own entry: left alone (delete it in Settings,
                    so one keypress cannot lose a friend's name)
        "forgot"  - learned usage removed; the phrase ranks as before
        "blocked" - nothing learned to forget: never suggest it again
                    (restorable in Settings)"""
        row = self._con.execute(
            "SELECT id, source, count, blocked FROM entries WHERE phrase=? AND reading=?", (phrase, reading)
        ).fetchone()
        if row is not None and row[1] == "manual" and not row[3]:
            return "manual"
        if row is not None and row[1] == "learned" and row[2] > 0 and not row[3]:
            self._con.execute("DELETE FROM entries WHERE id=?", (row[0],))
            self._load()
            return "forgot"
        self.block(phrase, reading, kind)
        return "blocked"

    def block(self, phrase: str, reading: str, kind: str = "zh") -> None:
        now = time.time()
        self._con.execute(
            "INSERT INTO entries (phrase, reading, kind, source, count, created, blocked) "
            "VALUES (?, ?, ?, 'learned', 0, ?, 1) "
            "ON CONFLICT (phrase, reading) DO UPDATE SET blocked = 1, count = 0",
            (phrase, reading, kind, now),
        )
        self._load()

    # ------------------------------------------------------------ management (settings app)
    def categories(self) -> list[dict]:
        rows = self._con.execute(
            "SELECT c.id, c.name, c.sort, (SELECT count(*) FROM entries e WHERE e.category_id = c.id AND e.blocked = 0) "
            "FROM categories c ORDER BY c.sort, c.id"
        ).fetchall()
        return [{"id": r[0], "name": r[1], "sort": r[2], "entries": r[3]} for r in rows]

    def add_category(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("category name is empty")
        sort = self._con.execute("SELECT coalesce(max(sort), 0) + 1 FROM categories").fetchone()[0]
        cur = self._con.execute("INSERT INTO categories (name, sort) VALUES (?, ?)", (name, sort))
        return int(cur.lastrowid)

    def rename_category(self, cat_id: int, name: str) -> None:
        self._con.execute("UPDATE categories SET name=? WHERE id=?", (name.strip(), cat_id))
        self._load()

    def delete_category(self, cat_id: int) -> None:
        self._con.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        self._load()

    def _category_id(self, name: str | None) -> int | None:
        if not name:
            return None
        row = self._con.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()
        return row[0] if row else self.add_category(name)

    def add(self, phrase: str, reading: str, kind: str = "zh", category: str | None = None) -> int:
        """Add (or promote to) a manual entry."""
        phrase = phrase.strip()
        if not phrase:
            raise ValueError("phrase is empty")
        now = time.time()
        cat_id = self._category_id(category)
        self._con.execute(
            "INSERT INTO entries (phrase, reading, kind, category_id, source, count, created) "
            "VALUES (?, ?, ?, ?, 'manual', 0, ?) "
            "ON CONFLICT (phrase, reading) DO UPDATE SET source='manual', blocked=0, "
            "category_id=coalesce(excluded.category_id, category_id)",
            (phrase, reading, kind, cat_id, now),
        )
        self._load()
        return self._con.execute("SELECT id FROM entries WHERE phrase=? AND reading=?", (phrase, reading)).fetchone()[0]

    def update(self, entry_id: int, *, category: str | None = None, reading: str | None = None,
               blocked: bool | None = None) -> None:
        if category is not None:
            self._con.execute("UPDATE entries SET category_id=?, source='manual' WHERE id=?",
                              (self._category_id(category), entry_id))
        if reading is not None:
            self._con.execute("UPDATE entries SET reading=? WHERE id=?", (reading, entry_id))
        if blocked is not None:
            self._con.execute("UPDATE entries SET blocked=? WHERE id=?", (int(blocked), entry_id))
        self._load()

    def delete(self, entry_id: int) -> None:
        self._con.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        self._load()

    # The settings page's two areas: what the IME collected by itself and
    # the user has not sorted yet, and the user's own curated words.
    VIEWS = {
        "inbox": "e.blocked = 0 AND e.category_id IS NULL AND e.source = 'learned'",
        "mine": "e.blocked = 0 AND (e.category_id IS NOT NULL OR e.source = 'manual')",
        "blocked": "e.blocked = 1",
    }
    SORTS = {
        "recent": "coalesce(e.last_used, e.created) DESC, e.id DESC",
        "count": "e.count DESC, coalesce(e.last_used, e.created) DESC",
        "phrase": "e.phrase",
        "default": "e.blocked, e.source = 'learned', e.count DESC, e.created DESC",
    }

    def _where(self, view: str | None, category: str | None, source: str | None, blocked: bool | None,
               query: str) -> tuple[str, list]:
        where, args = [], []
        if view in self.VIEWS:
            where.append(self.VIEWS[view])
        if category:
            where.append("c.name = ?")
            args.append(category)
        if source:
            where.append("e.source = ?")
            args.append(source)
        if blocked is not None:
            where.append("e.blocked = ?")
            args.append(int(blocked))
        if query:
            where.append("(e.phrase LIKE ? OR e.reading LIKE ?)")
            args += [f"%{query}%", f"%{query}%"]
        return ("WHERE " + " AND ".join(where) if where else ""), args

    def list(self, *, view: str | None = None, category: str | None = None, source: str | None = None,
             blocked: bool | None = None, query: str = "", sort: str = "default", limit: int = 500,
             offset: int = 0) -> list[dict]:
        where, args = self._where(view, category, source, blocked, query)
        sql = f"{where} ORDER BY {self.SORTS.get(sort, self.SORTS['default'])} LIMIT ? OFFSET ?"
        return [vars(e) for e in self._entries(sql, tuple(args + [limit, max(0, offset)]))]

    def count(self, *, view: str | None = None, category: str | None = None, source: str | None = None,
              blocked: bool | None = None, query: str = "") -> int:
        where, args = self._where(view, category, source, blocked, query)
        return self._con.execute(
            "SELECT count(*) FROM entries e LEFT JOIN categories c ON c.id = e.category_id " + where, args
        ).fetchone()[0]

    def stats(self) -> dict:
        r = self._con.execute(
            "SELECT sum(source='manual' AND blocked=0), sum(source='learned' AND blocked=0), sum(blocked) FROM entries"
        ).fetchone()
        size = sum(p.stat().st_size for p in (self.path, self.path.with_name(self.path.name + "-wal"))
                   if p.exists())
        return {"manual": r[0] or 0, "learned": r[1] or 0, "blocked": r[2] or 0, "bytes": size,
                "inbox": self.count(view="inbox"), "mine": self.count(view="mine")}

    def tidy(self, days: int = TIDY_AFTER_DAYS, compact: bool = False) -> int:
        """Forget learned words used once and not since ``days`` ago.
        ``compact`` also shrinks the file (VACUUM; skipped if it is busy)."""
        cutoff = time.time() - days * 86400
        cur = self._con.execute(
            "DELETE FROM entries WHERE source='learned' AND blocked=0 AND count<=1 "
            "AND coalesce(last_used, created, 0) < ?", (cutoff,))
        removed = cur.rowcount
        if removed:
            self._load()
        if compact:
            try:
                self._con.execute("VACUUM")
            except sqlite3.OperationalError:
                pass  # the IME is writing right now; next time
        return removed

    def clear_learned(self) -> int:
        cur = self._con.execute("DELETE FROM entries WHERE source='learned' AND blocked=0")
        self._con.execute("UPDATE entries SET count=0 WHERE source='manual'")
        self._load()
        return cur.rowcount

    # ------------------------------------------------------------ export / import
    def backup_to(self, path: str | Path) -> None:
        dst = sqlite3.connect(path)
        with dst:
            self._con.backup(dst)
        dst.close()

    def merge_from(self, path: str | Path) -> int:
        """Merge another user.db (import "my memory" from another PC):
        manual entries and categories are added, usage counts are summed,
        blocks are kept."""
        src = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        n = 0
        try:
            cats = dict(src.execute("SELECT id, name FROM categories").fetchall())
            for name in cats.values():
                self._con.execute("INSERT OR IGNORE INTO categories (name, sort) VALUES (?, 99)", (name,))
            has_origin = "origin" in {r[1] for r in src.execute("PRAGMA table_info(entries)")}
            origin_col = "origin" if has_origin else "''"
            for phrase, reading, kind, cat_id, source, count, last_used, created, blocked, origin in src.execute(
                "SELECT phrase, reading, kind, category_id, source, count, last_used, created, blocked, "
                f"{origin_col} FROM entries"
            ):
                my_cat = self._category_id(cats.get(cat_id)) if cat_id in cats else None
                self._con.execute(
                    "INSERT INTO entries (phrase, reading, kind, category_id, source, count, last_used, created, "
                    "blocked, origin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (phrase, reading) DO UPDATE SET "
                    "count = count + excluded.count, "
                    "source = CASE WHEN excluded.source='manual' THEN 'manual' ELSE source END, "
                    "category_id = coalesce(category_id, excluded.category_id), "
                    "blocked = max(blocked, excluded.blocked), "
                    "origin = CASE WHEN origin = '' THEN excluded.origin ELSE origin END, "
                    "last_used = max(coalesce(last_used, 0), coalesce(excluded.last_used, 0))",
                    (phrase, reading, kind, my_cat, source, count, last_used, created or time.time(), blocked,
                     origin or ""),
                )
                n += 1
        finally:
            src.close()
        self._load()
        return n

    def close(self) -> None:
        self._con.close()
