"""Per-input-context state machine.

The session owns the uncommitted *key buffer*. Everything shown in the
composition is derived from it by the decoder, so editing is always done on
raw keys and the interpretation can change as more context arrives.

UX (mode B agreed in Phase 2): looks like 華碩智慧輸入法 — typed letters show
inline, the zhuyin of an unfinished syllable is shown as a hint, a tone key
turns it into Chinese — but text stays in the composition (underlined) until
Enter / clause punctuation / overflow, so earlier characters can still be
fixed with the candidate window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum

from ..config import Config
from . import bopomofo
from .decoder import CLAUSE_PUNCT, FULLWIDTH_PUNCT, PUNCT_VARIANTS, Decoder, Decoding, Key, Kind, Segment
from .keys import (
    MODIFIER_VKS, SCAN_LSHIFT, SCAN_RSHIFT, VK_BACK, VK_DELETE, VK_DOWN, VK_END, VK_ESCAPE,
    VK_HOME, VK_LEFT, VK_NEXT, VK_OEM_1, VK_OEM_2, VK_OEM_4, VK_OEM_6, VK_OEM_7, VK_OEM_COMMA,
    VK_OEM_MINUS, VK_OEM_PERIOD, VK_PRIOR, VK_RETURN, VK_RIGHT, VK_SHIFT, VK_SPACE, VK_TAB,
    VK_UP, KeyInput,
)
from .layouts import Layout
from .lexicon import Lexicon

SHIFT_TAP_SECONDS = 0.5
SELECTION_DIGITS = "123456789"
SINGLE_CHAR_SUGGEST_MARGIN = 1.5  # stricter autocomplete threshold for 1-char context

# Ctrl(+Shift)+key -> full-width punctuation, following 微軟新注音 (華碩 uses
# the same convention). Key: (virtual key, shift held).
CTRL_PUNCT = {
    (VK_OEM_COMMA, False): "，", (VK_OEM_PERIOD, False): "。", (VK_OEM_1, False): "；",
    (VK_OEM_7, False): "、", (VK_OEM_2, False): "…", (VK_OEM_MINUS, False): "—",
    (VK_OEM_4, False): "「", (VK_OEM_6, False): "」",
    (VK_OEM_COMMA, True): "《", (VK_OEM_PERIOD, True): "》", (VK_OEM_1, True): "：",
    (VK_OEM_7, True): "＂", (VK_OEM_2, True): "？", (0x31, True): "！",
    (VK_OEM_4, True): "『", (VK_OEM_6, True): "』", (0x39, True): "（", (0x30, True): "）",
}

# Keys we consume while composing even though they produce no character.
_COMPOSING_NAV = frozenset(
    {VK_BACK, VK_DELETE, VK_RETURN, VK_ESCAPE, VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN,
     VK_HOME, VK_END, VK_TAB}
)


class Mode(str, Enum):
    AUTO = "auto"  # 中英自動：解碼器自行判斷中文或英文（預設）
    CHINESE = "chinese"  # 純中文：每個鍵都是注音（數字請用數字鍵盤）
    ENGLISH = "english"  # 純英文：按鍵直接交給應用程式

    @property
    def label(self) -> str:
        return {"auto": "中英自動", "chinese": "純中文", "english": "純英文"}[self.value]


@dataclass
class Candidate:
    text: str
    pin: Segment
    annotation: str = ""


@dataclass
class CandidateList:
    items: list[Candidate]
    page_size: int
    index: int = 0

    @property
    def page(self) -> int:
        return self.index // self.page_size

    def page_items(self) -> list[Candidate]:
        start = self.page * self.page_size
        return self.items[start:start + self.page_size]

    def move(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.items)

    def move_page(self, delta: int) -> None:
        pages = (len(self.items) + self.page_size - 1) // self.page_size
        page = (self.page + delta) % pages
        self.index = page * self.page_size


@dataclass
class Suggestion:
    text: str  # what Tab will append
    pin: Segment  # the full phrase pinned after accepting
    keys: list[Key]  # keys appended to the buffer


@dataclass
class View:
    """Everything a frontend needs to render after an event."""

    composition: str = ""
    cursor: int = 0
    commit: str = ""
    candidates: list[str] | None = None
    candidate_index: int = 0
    hint: str = ""
    suggestion: str = ""
    mode: Mode = Mode.AUTO


@dataclass
class Engine:
    """Shared, read-only resources for all sessions in the process."""

    lexicon: Lexicon
    layout: Layout
    decoder: Decoder
    config: Config


class Session:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.cfg = engine.config
        self.mode = Mode(self.cfg.start_mode)
        # The Chinese-side mode a Shift tap returns to from English.
        self.chinese_mode = self.mode if self.mode is not Mode.ENGLISH else Mode.AUTO
        self.keys: list[Key] = []
        self.pins: list[Segment] = []
        self.cursor = 0  # position in self.keys
        self.decoding = Decoding((), 0.0)
        self.cand: CandidateList | None = None
        self.suggestion: Suggestion | None = None
        self._commit = ""
        self._shift_down_at: float | None = None
        self._shift_scan = 0

    # ================================================================ API
    @property
    def composing(self) -> bool:
        return bool(self.keys)

    def view(self) -> View:
        units = self.decoding.units()
        cursor_chars = sum(1 for a, b, _, _ in units if b <= self.cursor)
        v = View(
            composition=self.decoding.text,
            cursor=cursor_chars,
            commit=self._commit,
            mode=self.mode,
        )
        self._commit = ""
        if self.cand is not None:
            v.candidates = [c.text for c in self.cand.page_items()]
            v.candidate_index = self.cand.index % self.cand.page_size
        else:
            v.hint = self._hint()
            if not v.hint and self.suggestion is not None:
                v.suggestion = self.suggestion.text
        return v

    def filter_key_down(self, key: KeyInput) -> bool:
        if key.vk == VK_SHIFT:
            self._shift_down_at = time.monotonic()
            self._shift_scan = key.scan
        else:
            self._shift_down_at = None
        return self._wants(key)

    def key_down(self, key: KeyInput) -> bool:
        if not self._wants(key):
            return False
        if self.cand is not None:
            if self._candidate_key(key):
                return True
            self.cand = None  # any other key closes the window and is typed
        return self._edit_key(key)

    def filter_key_up(self, key: KeyInput) -> bool:
        return self._is_shift_tap(key)

    def key_up(self, key: KeyInput) -> bool:
        if not self._is_shift_tap(key):
            return False
        self._shift_down_at = None
        self.toggle_mode()
        return True

    def toggle_mode(self) -> None:
        """Shift tap. Default: English <-> the Chinese-side mode used last.
        With ``shift_cycle = "three"``: 自動 -> 純中文 -> 純英文 -> 自動."""
        if self.cfg.shift_cycle == "three":
            order = [Mode.AUTO, Mode.CHINESE, Mode.ENGLISH]
            self.set_mode(order[(order.index(self.mode) + 1) % len(order)])
        else:
            self.set_mode(self.chinese_mode if self.mode is Mode.ENGLISH else Mode.ENGLISH)

    def set_mode(self, mode: Mode) -> None:
        self.commit_all()
        self.mode = mode
        if mode is not Mode.ENGLISH:
            self.chinese_mode = mode

    def commit_all(self) -> None:
        self.cand = None
        if self.keys:
            self._commit += self.decoding.text
        self._reset_buffer()

    def reset(self) -> None:
        """Composition was terminated by the app (focus change, click, ...)."""
        self.cand = None
        self._reset_buffer()

    # ========================================================= key routing
    def _ctrl_punct(self, key: KeyInput) -> str | None:
        if not (key.ctrl and not key.alt and self.cfg.ctrl_punctuation and self.mode is not Mode.ENGLISH):
            return None
        return CTRL_PUNCT.get((key.vk, key.shift))

    def _wants(self, key: KeyInput) -> bool:
        if key.vk in MODIFIER_VKS:
            return False
        if self.cand is not None:
            return True
        if self._ctrl_punct(key) is not None:
            return True
        if key.ctrl or key.alt:
            return False
        if self.mode is Mode.ENGLISH:
            return False
        if not self.composing:
            if not key.printable or key.char == " " or key.numpad:
                return False
            if key.caps and key.char.isalpha():
                return False  # Caps Lock = typing English capitals
            return True
        return key.vk in _COMPOSING_NAV or key.printable

    def _is_shift_tap(self, key: KeyInput) -> bool:
        if key.vk != VK_SHIFT or self._shift_down_at is None:
            return False
        if time.monotonic() - self._shift_down_at > SHIFT_TAP_SECONDS:
            return False
        which = self.cfg.toggle_shift
        if which == "none":
            return False
        if which == "left" and self._shift_scan not in (SCAN_LSHIFT, 0):
            return False
        if which == "right" and self._shift_scan not in (SCAN_RSHIFT, 0):
            return False
        return True

    def _edit_key(self, key: KeyInput) -> bool:
        vk = key.vk
        punct = self._ctrl_punct(key)
        if punct is not None:
            # Inserted as a key whose character *is* the punctuation, so it
            # flows through the decoder (and clause punctuation commits).
            self._insert(Key(punct))
            return True
        if vk == VK_RETURN:
            self.commit_all()
        elif vk == VK_ESCAPE:
            self._reset_buffer()
        elif vk == VK_BACK:
            self._delete_unit(before=True)
        elif vk == VK_DELETE:
            self._delete_unit(before=False)
        elif vk == VK_LEFT:
            self._move_unit(-1)
        elif vk == VK_RIGHT:
            self._move_unit(+1)
        elif vk == VK_HOME:
            self.cursor = 0
            self._refresh()
        elif vk == VK_END:
            self.cursor = len(self.keys)
            self._refresh()
        elif vk in (VK_UP, VK_DOWN):
            self._open_candidates()
        elif vk == VK_TAB:
            if self.suggestion is not None:
                self._accept_suggestion()
            else:
                self.commit_all()
        elif key.printable:
            self._insert(Key(key.char, key.numpad))
        else:
            return False
        return True

    # ============================================================ editing
    def _insert(self, k: Key) -> None:
        pos = self.cursor
        self.keys.insert(pos, k)
        kept = []
        for p in self.pins:
            if p.start >= pos:
                kept.append(_shift_segment(p, 1))
            elif p.end <= pos:
                kept.append(p)
            # a pin that spans the insertion point is dropped
        self.pins = kept
        self.cursor = pos + 1
        self._redecode()
        if self.cfg.commit_on_clause_punct and self.cursor == len(self.keys):
            last = self.decoding.segments[-1] if self.decoding.segments else None
            if last is not None and last.kind is Kind.PUNCT and last.text in CLAUSE_PUNCT:
                self.commit_all()
                return
        self._commit_overflow()

    def _delete_keys(self, a: int, b: int) -> None:
        del self.keys[a:b]
        width = b - a
        kept = []
        for p in self.pins:
            if p.end <= a:
                kept.append(p)
            elif p.start >= b:
                kept.append(_shift_segment(p, -width))
        self.pins = kept
        if self.cursor >= b:
            self.cursor -= width
        elif self.cursor > a:
            self.cursor = a

    def _delete_unit(self, before: bool) -> None:
        units = self.decoding.units()
        target = None
        for a, b, _, seg_idx in units:
            if (before and b == self.cursor) or (not before and a == self.cursor):
                target = (a, b, seg_idx)
                break
        if target is None:
            # Dropped (invisible) keys sit next to the cursor: delete them
            # together with the neighbouring character so the keypress has a
            # visible effect.
            if before and self.cursor > 0:
                prev = [a for a, b, _, _ in units if b < self.cursor]
                self._delete_keys(prev[-1] if prev else 0, self.cursor)
            elif not before and self.cursor < len(self.keys):
                nxt = [b for a, b, _, _ in units if a > self.cursor]
                self._delete_keys(self.cursor, nxt[0] if nxt else len(self.keys))
            else:
                return
            if not self.keys:
                self._reset_buffer()
            else:
                self._redecode()
            return
        a, b, seg_idx = target
        seg = self.decoding.segments[seg_idx]
        if seg.kind is Kind.PENDING and before:
            a = b - 1  # unfinished syllable: delete one key at a time
        self._delete_keys(a, b)
        if not self.keys:
            self._reset_buffer()
        else:
            self._redecode()

    def _move_unit(self, delta: int) -> None:
        units = self.decoding.units()
        if delta < 0:
            prev = [a for a, b, _, _ in units if b <= self.cursor]
            self.cursor = prev[-1] if prev else 0
        else:
            nxt = [b for a, b, _, _ in units if a >= self.cursor]
            self.cursor = nxt[0] if nxt else len(self.keys)
        self._refresh()

    def _commit_overflow(self) -> None:
        """Keep the composition from growing without bound.

        Never fires while a syllable is still being typed (that would decide
        the earlier text without the context of the syllable). When it fires,
        it commits down to well below the limit, so partial commits — each one
        ends and restarts the TSF composition — stay rare.
        """
        limit = self.cfg.max_buffer_chars
        segs = self.decoding.segments
        if len(self.decoding.units()) <= limit or not segs or segs[-1].kind is Kind.PENDING:
            return
        target = max(limit // 2, limit - 10)
        while len(self.decoding.units()) > target and len(self.decoding.segments) > 1:
            first = self.decoding.segments[0]
            if first.end > self.cursor:
                break
            self._commit += first.text
            self._delete_keys(0, first.end)
            self._redecode()

    def _reset_buffer(self) -> None:
        self.keys.clear()
        self.pins.clear()
        self.cursor = 0
        self.decoding = Decoding((), 0.0)
        self.suggestion = None

    def _redecode(self) -> None:
        self.decoding = self.engine.decoder.decode(self.keys, self.pins, allow_english=self.mode is Mode.AUTO)
        self._snap_cursor()
        self._update_suggestion()

    def _refresh(self) -> None:
        self._snap_cursor()
        self._update_suggestion()

    def _snap_cursor(self) -> None:
        self.cursor = max(0, min(self.cursor, len(self.keys)))
        for a, b, _, _ in self.decoding.units():
            if a < self.cursor < b:
                self.cursor = b
                break

    # ========================================================= candidates
    def _target_unit(self) -> int | None:
        units = self.decoding.units()
        if not units:
            return None
        if self.cursor >= len(self.keys):
            # At the end: the last real character (skip trailing spaces, so
            # "mvp␣" + ↓ offers alternatives for mvp).
            segs = self.decoding.segments
            idx = len(units) - 1
            while idx > 0 and segs[units[idx][3]].kind is Kind.SPACE:
                idx -= 1
            return idx
        for idx, (a, _, _, _) in enumerate(units):
            if a >= self.cursor:
                return idx
        return len(units) - 1

    def _open_candidates(self) -> None:
        t = self._target_unit()
        if t is None:
            return
        units = self.decoding.units()
        a, b, _, seg_idx = units[t]
        seg = self.decoding.segments[seg_idx]
        # Candidates cross categories: Chinese <-> English <-> the raw keys,
        # so any wrong guess (o␣ vs ㄟ, i␣ vs 喔, mvp vs 勳) is one pick away.
        if seg.kind is Kind.ZH:
            items = self._zh_candidates(units, t, at_end=self.cursor >= len(self.keys))
            items += self._raw_candidates(a, b)
        elif seg.kind is Kind.EN:
            items = _en_candidates(seg) + self._zh_alternatives(seg.start)
        elif seg.kind is Kind.PUNCT:
            items = self._punct_candidates(seg)
        elif seg.kind in (Kind.NUM, Kind.LITERAL):
            items = [Candidate(seg.text, replace(seg, pinned=True))] + self._zh_alternatives(seg.start)
        else:
            items = []
        seen: set[tuple[str, int, int]] = set()
        unique = []
        for c in items:
            key = (c.text, c.pin.start, c.pin.end)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        if unique:
            self.cand = CandidateList(unique, self.cfg.candidates_per_page)

    def _zh_alternatives(self, start: int) -> list[Candidate]:
        return [Candidate(s.text, replace(s, pinned=True))
                for s in self.engine.decoder.zh_alternatives(self.keys, start)]

    def _dropped_before(self, pos: int) -> int:
        """Start of the run of dropped (invisible) keys that ends at ``pos``."""
        dropped_ends = {s.end: s.start for s in self.decoding.segments if s.kind is Kind.DROP}
        while pos in dropped_ends:
            pos = dropped_ends[pos]
        return pos

    def _raw_candidates(self, a: int, b: int) -> list[Candidate]:
        """The keys exactly as typed (including stray keys dropped just
        before them), to undo any interpretation."""
        a = self._dropped_before(a)
        raw = "".join(k.char for k in self.keys[a:b])
        return [Candidate(raw, Segment(a, b, raw, Kind.LITERAL, -10.0, pinned=True), annotation="原始按鍵")]

    def _zh_candidates(self, units, t: int, at_end: bool) -> list[Candidate]:
        segs = self.decoding.segments
        # Maximal run of consecutive Chinese characters around the target.
        lo = t
        while lo > 0 and segs[units[lo - 1][3]].kind is Kind.ZH:
            lo -= 1
        hi = t
        while hi + 1 < len(units) and segs[units[hi + 1][3]].kind is Kind.ZH:
            hi += 1
        run = units[lo:hi + 1]
        readings = []
        for a, b, _, seg_idx in run:
            seg = segs[seg_idx]
            readings.append(seg.readings[seg.bounds.index(a)])
        ti = t - lo
        max_len = self.engine.lexicon.max_phrase_syllables
        spans = []
        if at_end:
            for length in range(min(max_len, ti + 1), 0, -1):
                spans.append((ti - length + 1, ti + 1))
        else:
            for length in range(min(max_len, len(run) - ti), 0, -1):
                spans.append((ti, ti + length))
        seen = set()
        items: list[Candidate] = []
        for s, e in spans:
            rs = tuple(readings[s:e])
            bounds = tuple(run[i][0] for i in range(s, e)) + (run[e - 1][1],)
            for text, score in self.engine.lexicon.phrases("-".join(rs)):
                key = (text, bounds[0], bounds[-1])
                if key in seen:
                    continue
                seen.add(key)
                pin = Segment(bounds[0], bounds[-1], text, Kind.ZH, score, rs, bounds, pinned=True)
                items.append(Candidate(text, pin))
        return items

    def _punct_candidates(self, seg: Segment) -> list[Candidate]:
        raw = self.keys[seg.start].char
        options = [seg.text]  # current choice first, then the other style
        if raw in FULLWIDTH_PUNCT:
            options += [FULLWIDTH_PUNCT[raw], raw, *PUNCT_VARIANTS.get(raw, "")]
        return [Candidate(o, replace(seg, text=o, pinned=True)) for o in dict.fromkeys(options)]

    def _candidate_key(self, key: KeyInput) -> bool:
        cand = self.cand
        assert cand is not None
        vk = key.vk
        if key.char and key.char in SELECTION_DIGITS and not key.numpad:
            i = SELECTION_DIGITS.index(key.char)
            page = cand.page_items()
            if i < len(page):
                self._choose(page[i])
            return True
        if vk in (VK_RETURN, VK_SPACE):
            self._choose(cand.items[cand.index])
        elif vk == VK_DOWN:
            cand.move(+1)
        elif vk == VK_UP:
            cand.move(-1)
        elif vk in (VK_RIGHT, VK_NEXT):
            cand.move_page(+1)
        elif vk in (VK_LEFT, VK_PRIOR):
            cand.move_page(-1)
        elif vk in (VK_ESCAPE, VK_BACK):
            self.cand = None
        else:
            return False
        return True

    def _choose(self, c: Candidate) -> None:
        pin = c.pin
        self.pins = [p for p in self.pins if p.end <= pin.start or p.start >= pin.end]
        self.pins.append(pin)
        self.pins.sort(key=lambda p: p.start)
        self.cand = None
        if self.cursor < len(self.keys):
            self.cursor = pin.end
        self._redecode()

    # ========================================================= assistance
    def _hint(self) -> str:
        if not self.cfg.spelling_hint or not self.decoding.segments:
            return ""
        layout = self.engine.layout
        last = self.decoding.segments[-1]
        if self.cursor == len(self.keys):
            if last.kind is Kind.PENDING:
                # Show what the keys will become, in canonical order (k2 -> ㄉㄜ).
                canon = bopomofo.canonical(layout.symbol(c) or "" for c in last.text)
                return canon or layout.symbols_for_keys(last.text)
            return ""
        # Cursor moved back to fix something: annotate the character after
        # the cursor with its reading and the keys behind it, so stray
        # letters and wrong guesses are easy to spot.
        t = self._target_unit()
        if t is None:
            return ""
        a, b, ch, seg_idx = self.decoding.units()[t]
        seg = self.decoding.segments[seg_idx]
        start = self._dropped_before(a)
        dropped = "".join(k.char for k in self.keys[start:a])
        raw = "".join(k.char for k in self.keys[a:b])
        if seg.kind is Kind.ZH:
            text = f"{ch} {seg.readings[seg.bounds.index(a)]}  ⌨ {raw}"
        else:
            sym = layout.symbol(raw) or layout.tone(raw)
            text = f"{ch}  ⌨ {raw}" + (f"（ㄅ: {sym}）" if sym else "")
        if dropped:
            text = f"（略過 {dropped}）" + text
        return text

    def _update_suggestion(self) -> None:
        self.suggestion = None
        if not self.cfg.autocomplete or self.cand is not None or self.cursor != len(self.keys):
            return
        segs = self.decoding.segments
        if not segs or segs[-1].kind is not Kind.ZH:
            return
        units = self.decoding.units()
        run = []  # (key_start, key_end, char, reading) of trailing Chinese chars
        for a, b, ch, seg_idx in reversed(units):
            seg = segs[seg_idx]
            if seg.kind is not Kind.ZH:
                break
            run.append((a, b, ch, seg.readings[seg.bounds.index(a)]))
            if len(run) == 3:
                break
        run.reverse()
        lex = self.engine.lexicon
        layout = self.engine.layout
        for k in range(len(run), 0, -1):
            tail = run[-k:]
            prefix = "".join(u[2] for u in tail)
            prefix_reading = "-".join(u[3] for u in tail)
            # A single character is weak context; only suggest common phrases.
            min_score = self.cfg.autocomplete_min_score + (SINGLE_CHAR_SUGGEST_MARGIN if k == 1 else 0.0)
            for phrase, reading, score in lex.completions(prefix):
                if score < min_score:
                    break
                if not reading.startswith(prefix_reading + "-") or len(phrase) - k > 3:
                    continue
                extra = reading.split("-")[k:]
                keys = [Key(c) for syl in extra for c in layout.keys_for_syllable(syl)]
                bounds = [u[0] for u in tail] + [tail[-1][1]]
                pos = tail[-1][1]
                for syl in extra:
                    pos += len(layout.keys_for_syllable(syl))
                    bounds.append(pos)
                pin = Segment(tail[0][0], pos, phrase, Kind.ZH, score,
                              tuple(reading.split("-")), tuple(bounds), pinned=True)
                self.suggestion = Suggestion(phrase[k:], pin, keys)
                return

    def _accept_suggestion(self) -> None:
        sug = self.suggestion
        assert sug is not None
        start = len(self.keys)
        self.keys.extend(sug.keys)
        pin = sug.pin
        self.pins = [p for p in self.pins if p.end <= pin.start]
        self.pins.append(pin)
        self.cursor = len(self.keys)
        assert pin.end == start + len(sug.keys)
        self._redecode()
        self._commit_overflow()


def _shift_segment(seg: Segment, delta: int) -> Segment:
    return replace(
        seg,
        start=seg.start + delta,
        end=seg.end + delta,
        bounds=tuple(b + delta for b in seg.bounds),
    )


def _en_candidates(seg: Segment) -> list[Candidate]:
    word = seg.text
    variants = dict.fromkeys([word, word.lower(), word.upper(), word[:1].upper() + word[1:].lower()])
    return [Candidate(v, replace(seg, text=v, pinned=True)) for v in variants]
