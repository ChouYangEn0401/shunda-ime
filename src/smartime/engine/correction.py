"""Correction mode (Vim-like), mixed into Session.

Esc while composing enters it; the composition stays, and the keys become
commands instead of text. The cursor sits *on* a character (the unit after
it). Three views of the same buffer:

    國字  我更快的打字
    注音  ㄨㄛˇ ㄍㄥˋ ㄎㄨㄞˋ ㄉㄜ˙ ㄉㄚˇ ㄗˋ
    按鍵  ji3ee/4dj94k27283y4      <- stray keys are visible here

Commands: h/l move · j/k swap in the next/previous candidate in place ·
v next view · x delete (one key in the 按鍵 view) · e Chinese <-> English/raw
· r retype one character · a add the word to my dictionary · u undo ·
i back to typing · Enter commit · Esc clear everything.

Cycling with j/k does not teach the memory every candidate it passes; only
the final choice is learned, when the cursor leaves it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .decoder import Kind, Segment
from .keys import (
    VK_BACK, VK_DELETE, VK_DOWN, VK_END, VK_ESCAPE, VK_HOME, VK_LEFT, VK_RETURN, VK_RIGHT, VK_TAB, VK_UP,
    KeyInput,
)

LAYERS = ("text", "zhuyin", "keys")
LAYER_LABEL = {"text": "國字", "zhuyin": "注音", "keys": "按鍵"}
HELP = "h l 移動 · j k 換字 · v 檢視 · x 刪 · e 中英 · r 重打 · a 加詞 · u 復原 · i 打字"


@dataclass
class _Cycle:
    start: int  # key position of the unit being cycled
    items: list  # Candidate objects
    index: int
    original: Segment | None  # what was there before cycling


class CorrectionMixin:
    # ------------------------------------------------------------ state
    def _init_correction(self) -> None:
        self.correcting = False
        self.layer = "text"
        self._undo: list[tuple] = []
        self._cycle: _Cycle | None = None

    def enter_correction(self) -> None:
        self.correcting = True
        self.layer = "text"
        self._undo.clear()
        self._cycle = None
        self.suggestion = None
        # at the end: the last real character (not a trailing space, so
        # "mvp␣" + Esc lands on mvp)
        t = self._target_unit()
        if t is not None:
            self.cursor = self.decoding.units()[t][0]
        self._snap_to_unit()

    def exit_correction(self) -> None:
        self._finish_cycle()
        self.correcting = False
        self.layer = "text"
        self._undo.clear()

    # ------------------------------------------------------------ cursor
    def _unit_starts(self) -> list[int]:
        return [a for a, _, _, _ in self.decoding.units()]

    def _snap_to_unit(self) -> None:
        """Put the cursor on a unit (or on a key in the 按鍵 view)."""
        if not self.keys:
            return
        if self.layer == "keys":
            self.cursor = max(0, min(self.cursor, len(self.keys) - 1))
            return
        starts = self._unit_starts()
        if not starts:
            self.cursor = 0
            return
        # the unit that contains the cursor, else the next one, else the last
        for a, b, _, _ in self.decoding.units():
            if a <= self.cursor < b:
                self.cursor = a
                return
        after = [a for a in starts if a >= self.cursor]
        self.cursor = after[0] if after else starts[-1]

    def _target(self) -> tuple[int, int, str, int] | None:
        units = self.decoding.units()
        for u in units:
            if u[0] >= self.cursor:
                return u
        return units[-1] if units else None

    # ------------------------------------------------------------ undo
    def _snapshot(self) -> None:
        self._undo.append((list(self.keys), list(self.pins), self.cursor, self.layer))
        del self._undo[:-50]

    def _restore(self) -> None:
        if not self._undo:
            self._notice = "沒有可以復原的修正"
            return
        self._cycle = None
        self.keys, self.pins, self.cursor, self.layer = self._undo.pop()
        self._redecode()
        self._snap_to_unit()

    # ------------------------------------------------------------ key handling
    def _correction_key(self, key: KeyInput) -> bool:
        vk, ch = key.vk, key.char
        if key.ctrl or key.alt:
            return False
        if vk in (VK_UP, VK_DOWN):
            self._finish_cycle()
            self._open_candidates()
            return True
        if vk == VK_RETURN:
            self.exit_correction()
            self.commit_all()
            return True
        if vk == VK_ESCAPE:
            self.exit_correction()
            self._reset_buffer()
            return True
        if vk == VK_TAB:
            return True
        if ch == "i":
            self.exit_correction()
            self._refresh()
            return True
        if ch == "h" or vk == VK_LEFT:
            self._move(-1)
        elif ch == "l" or vk == VK_RIGHT:
            self._move(+1)
        elif vk == VK_HOME:
            self._finish_cycle()
            self.cursor = 0
            self._snap_to_unit()
        elif vk == VK_END:
            self._finish_cycle()
            self.cursor = len(self.keys)
            self._snap_to_unit()
        elif ch == "j":
            self._cycle_candidate(+1)
        elif ch == "k":
            self._cycle_candidate(-1)
        elif ch == "v":
            self._finish_cycle()
            self.layer = LAYERS[(LAYERS.index(self.layer) + 1) % len(LAYERS)]
            self._snap_to_unit()
        elif ch == "x" or vk == VK_DELETE:
            self._delete_here()
        elif vk == VK_BACK:
            self._move(-1)
            self._delete_here()
        elif ch == "e":
            self._toggle_kind()
        elif ch == "r":
            self._retype()
        elif ch == "a":
            self._add_word_here()
        elif ch == "u":
            self._restore()
        else:
            self._notice = "修正模式：" + HELP
        return True

    def _move(self, delta: int) -> None:
        self._finish_cycle()
        if self.layer == "keys":
            self.cursor = max(0, min(len(self.keys) - 1, self.cursor + delta))
            return
        starts = self._unit_starts()
        if not starts:
            return
        if delta < 0:
            before = [a for a in starts if a < self.cursor]
            self.cursor = before[-1] if before else starts[0]
        else:
            after = [a for a in starts if a > self.cursor]
            self.cursor = after[0] if after else starts[-1]

    # ------------------------------------------------------------ commands
    def _delete_here(self) -> None:
        self._finish_cycle()
        if not self.keys:
            return
        self._snapshot()
        if self.layer == "keys":
            self._delete_keys(self.cursor, self.cursor + 1)
        else:
            t = self._target()
            if t is None:
                return
            a, b = self._dropped_before(t[0]), t[1]
            self._delete_keys(a, b)
            self.cursor = a
        if not self.keys:
            self.exit_correction()
            self._reset_buffer()
            return
        self._redecode()
        self._snap_to_unit()

    def _retype(self) -> None:
        """Delete this character's keys and type it again (insert mode)."""
        self._finish_cycle()
        t = self._target()
        if t is None:
            return
        self._snapshot()
        a = self._dropped_before(t[0])
        self._delete_keys(a, t[1])
        self.cursor = a
        self.exit_correction()
        if not self.keys:
            self._reset_buffer()
        else:
            self._redecode()
            self.cursor = a
        self._notice = "重打這個字，打完按 Esc 回到修正模式"

    def _toggle_kind(self) -> None:
        """Chinese <-> the raw keys / English for the segment under the cursor."""
        self._finish_cycle()
        t = self._target()
        if t is None:
            return
        seg = self.decoding.segments[t[3]]
        if seg.kind is Kind.ZH:
            # only the character under the cursor; the rest of the phrase is
            # decoded again on its own
            a, b = t[0], t[1]
            raw = "".join(k.char for k in self.keys[a:b])
            pin = Segment(a, b, raw, Kind.LITERAL, -10.0, pinned=True)
        else:
            alts = self.engine.decoder.zh_alternatives(self.keys, seg.start)
            if not alts:
                self._notice = "這段按鍵沒有中文讀法"
                return
            same_span = [s for s in alts if s.end == seg.end]
            pin = replace((same_span or alts)[0], pinned=True)
        self._snapshot()
        self._apply_pin(pin)

    def _add_word_here(self) -> None:
        """Add the run of Chinese characters around the cursor (≤ 8)."""
        self._finish_cycle()
        units = self.decoding.units()
        t = self._target()
        if t is None:
            return
        segs = self.decoding.segments
        idx = units.index(t)
        if segs[t[3]].kind is not Kind.ZH:
            self._notice = "游標上不是中文"
            return
        lo = idx
        while lo > 0 and segs[units[lo - 1][3]].kind is Kind.ZH and idx - lo < 7:
            lo -= 1
        hi = idx
        while hi + 1 < len(units) and segs[units[hi + 1][3]].kind is Kind.ZH and hi - lo < 7:
            hi += 1
        run = units[lo:hi + 1]
        text = "".join(u[2] for u in run)
        reading = "-".join(segs[u[3]].readings[segs[u[3]].bounds.index(u[0])] for u in run)
        self._add_to_dict(text, reading, "zh")

    # ------------------------------------------------------------ j / k
    def _apply_pin(self, pin: Segment) -> None:
        self.pins = [p for p in self.pins if p.end <= pin.start or p.start >= pin.end]
        self.pins.append(pin)
        self.pins.sort(key=lambda p: p.start)
        self._redecode()
        self.cursor = pin.start
        self._snap_to_unit()

    def _cycle_candidate(self, step: int) -> None:
        t = self._target()
        if t is None:
            return
        if self._cycle is None or self._cycle.start != t[0]:
            self._finish_cycle()
            items = self._candidate_items()
            if not items:
                return
            current = self.decoding.segments[t[3]]
            self._snapshot()
            self._cycle = _Cycle(t[0], items, 0, current)
        c = self._cycle
        c.index = (c.index + step) % len(c.items)
        self._apply_pin(c.items[c.index].pin)
        self._cycle.start = self.cursor

    def _finish_cycle(self) -> None:
        """The cursor leaves a cycled character: learn the final choice."""
        c = self._cycle
        self._cycle = None
        if c is None or c.index == 0:
            return
        self._learn(c.items[c.index].pin)

    # ------------------------------------------------------------ rendering
    def _correction_view(self) -> tuple[str, int]:
        """(composition, cursor) for the current view."""
        if self.layer == "keys":
            return "".join("␣" if k.char == " " else k.char for k in self.keys), self.cursor
        if self.layer == "text":
            units = self.decoding.units()
            return self.decoding.text, sum(1 for a, b, _, _ in units if b <= self.cursor)
        out = ""
        cursor = 0
        segs = self.decoding.segments
        prev_zh = False
        for a, b, ch, seg_idx in self.decoding.units():
            seg = segs[seg_idx]
            is_zh = seg.kind is Kind.ZH
            if is_zh and prev_zh:
                out += " "
            if a == self.cursor or (a < self.cursor and b > self.cursor):
                cursor = len(out)
            out += seg.readings[seg.bounds.index(a)] if is_zh else ch
            prev_zh = is_zh
            if b <= self.cursor:
                cursor = len(out)
        return out, cursor

    def _correction_hint(self) -> str:
        label = f"【修正·{LAYER_LABEL[self.layer]}】"
        if self.layer == "keys" and self.keys:
            k = self.keys[self.cursor].char
            sym = self.engine.layout.symbol(k) or self.engine.layout.tone(k)
            dropped = any(s.kind is Kind.DROP and s.start == self.cursor for s in self.decoding.segments)
            info = f"⌨ {'␣' if k == ' ' else k}" + (f"（{sym or '一聲'}）" if sym is not None else "")
            if dropped:
                info += " 被略過的鍵"
            return f"{label}{info} · x 刪這個鍵 · v 換檢視 · i 打字"
        return f"{label}{self._unit_info()} · {HELP}"
