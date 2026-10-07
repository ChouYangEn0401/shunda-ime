"""Correction mode (Vim-like), mixed into Session.

Esc while composing enters it; the composition stays, and the keys become
commands instead of text. The cursor sits *on* a character (the unit after
it). Three views of the same buffer:

    國字  我更快的打字
    注音  ㄨㄛˇ ㄍㄥˋ ㄎㄨㄞˋ ㄉㄜ˙ ㄉㄚˇ ㄗˋ
    按鍵  ji3ee/4dj94k27283y4      <- stray keys are visible here

Commands: h/l move · j/k swap in the next/previous candidate in place ·
v next view · x delete (one key in the 按鍵 view) · e Chinese <-> English/raw
· r retype one character (back here by itself when it is done) · a add the
word to my dictionary · u undo · i or Esc back to typing · Enter commit ·
D twice: clear everything.

The mode is only left by an explicit command (i, Esc, Enter, D D, or a key
meant for the app such as Ctrl+V); other keys never type text by accident,
and the panel's amber frame shows the mode is on.

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
HELP = ("h l 移動 · j k 換字 · v 檢視 · x 刪 · e 中英 · r 重打 · R 重新判定 · a 加詞 · u 復原 · i／Esc 打字 · D D 清除")


@dataclass
class _Cycle:
    start: int  # key position of the unit being cycled
    items: list  # Candidate objects
    index: int
    original: Segment | None  # what was there before cycling
    original_text: str = ""  # the character(s) on screen before cycling


class CorrectionMixin:
    # ------------------------------------------------------------ state
    def _init_correction(self) -> None:
        self.correcting = False
        self.layer = "text"
        self._cycle: _Cycle | None = None
        self._clear_armed = False  # D pressed once: the next D clears everything
        self._retype_at: int | None = None  # r: typing one replacement character here
        self._redecide_span = 0  # R pressed in a row: how many extra units it covers

    def enter_correction(self) -> None:
        self.correcting = True
        self.layer = "text"
        self._cycle = None
        self._clear_armed = False
        self._retype_at = None
        self._redecide_span = 0
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
    # One history for the whole composition (Session._checkpoint): u in
    # correction mode and Ctrl+Z while typing undo the same steps.
    def _snapshot(self) -> None:
        self._checkpoint()

    def _restore(self, redo: bool = False) -> None:
        self._cycle = None
        if self.redo() if redo else self.undo():
            if self.correcting:
                self._snap_to_unit()

    # ------------------------------------------------------------ key handling
    def _correction_key(self, key: KeyInput) -> bool:
        vk, ch = key.vk, key.char
        armed, self._clear_armed = self._clear_armed, False
        if ch != "R":
            self._redecide_span = 0  # a run of R presses ended
        if key.ctrl and not key.alt and vk in (0x59, 0x5A):  # Ctrl+Y / Ctrl+Z
            self._restore(redo=vk == 0x59 or key.shift)
            return True
        if self._ctrl_punct(key) is not None:
            # no typing in correction mode (the frame says so); stay here
            self._notice = "修正模式中不打字：按 i 或 Esc 回到打字"
            return True
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
            # back to typing; nothing is lost (Esc again comes back here)
            self.exit_correction()
            self._refresh()
            return True
        if ch == "D":
            if armed:
                self.exit_correction()
                self._reset_buffer()
            else:
                self._clear_armed = True
                self._notice = "再按一次 D 清除整段（不會送出）"
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
        elif ch == "R":
            self._redecide()
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
            # deleting a raw key is meant to change how its neighbours read
            self._delete_range(self.cursor, self.cursor + 1, stable=False)
        else:
            t = self._target()
            if t is None:
                return
            a, b = self._dropped_before(t[0]), t[1]
            self._delete_range(a, b)
            self.cursor = a
        if not self.keys:
            self.exit_correction()
            self._reset_buffer()
            return
        self._snap_to_unit()

    def _retype(self) -> None:
        """Delete this character's keys and type it again; when the new
        syllable is complete, correction mode comes back by itself (like
        Vim's r). Esc returns early."""
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
        self._retype_at = a
        self._notice = "重打這個字：打完這個字自動回到修正模式"

    def _retype_done(self) -> None:
        """After a key typed in r mode: back to correction mode once the
        replacement is a finished Chinese character."""
        a = self._retype_at
        if a is None:
            return
        seg = next((s for s in self.decoding.segments if s.start <= a < s.end), None)
        if seg is not None and seg.kind is Kind.ZH and self.cursor in seg.bounds and self.cursor > a:
            self._retype_at = None
            self.correcting = True
            self.layer = "text"
            self._cycle = None
            self.cursor = a
            self._snap_to_unit()
            self.suggestion = None
            self.suggestions = []

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
            alts = self.engine.decoder.zh_alternatives(self.keys, seg.start, scheme=self.scheme)
            if not alts:
                self._notice = "這段按鍵沒有中文讀法"
                return
            same_span = [s for s in alts if s.end == seg.end]
            pin = replace((same_span or alts)[0], pinned=True)
        self._snapshot()
        self._apply_pin(pin)

    def _redecide(self) -> None:
        """R: throw away the choices made over this stretch and decode it again.

        Picking characters one by one pins them, and a pin the decoder has to
        honour can strand a key next to the syllable it belongs to: ``e`` is
        left as English in 「至 e 灣」 when ``ej0␣`` on its own is 關. Nothing
        in the mode could join them again — j/k offered no Chinese for a lone
        ``e``, and x would have thrown the key away.

        Each press in a row takes one more character in, so the span can be
        grown until the decoder sees enough context.
        """
        self._finish_cycle()
        units = self.decoding.units()
        t = self._target()
        if t is None or not units:
            self._notice = "沒有東西可以重新判定"
            return
        here = units.index(t)
        self._redecide_span += 1
        last = min(len(units) - 1, here + self._redecide_span)
        a, b = units[here][0], units[last][1]
        if not any(p.start < b and p.end > a for p in self.pins):
            if last == len(units) - 1 and here == 0:
                self._notice = "這一段沒有選過的字，解碼器本來就是這樣讀的"
                return
        self._snapshot()
        self.pins = [p for p in self.pins if p.end <= a or p.start >= b]
        self._redecode()
        self.cursor = a
        self._snap_to_unit()
        span = "".join(u[2] for u in self.decoding.units() if a <= u[0] < b)
        self._notice = f"重新判定「{span}」· 再按一次 R 多納入一個字"

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
            start = self._current_index(items)  # j/k walk away from what is on screen
            self._cycle = _Cycle(t[0], items, start, current, t[2])
        c = self._cycle
        # Step past candidates that would leave the screen looking the same.
        # The list holds both the word and its first character (今天 and 今),
        # so a plain +1 could pin a different span and change nothing visible
        # — which read as "the shortcut does not work".
        for _ in range(len(c.items)):
            c.index = (c.index + step) % len(c.items)
            cand = c.items[c.index]
            if cand.pin is not None and cand.text != self._text_over(cand.pin.start, cand.pin.end):
                break
        self._apply_pin(c.items[c.index].pin)
        self._cycle.start = self.cursor

    def _finish_cycle(self) -> None:
        """The cursor leaves a cycled character: learn the final choice."""
        c = self._cycle
        self._cycle = None
        if c is None:
            return
        pin = c.items[c.index].pin
        if pin is None or c.items[c.index].text == c.original_text:
            return  # back where it started: nothing to learn
        self._learn_choice(pin, c.original_text)

    # ------------------------------------------------------------ rendering
    # The composition always holds the real (Chinese) text; the 注音 and 按鍵
    # views are drawn in the hint box. If an app ends the composition at any
    # moment (some browser editors do), what lands in the document is the
    # text, never zhuyin or raw keys.

    def _correction_view(self) -> tuple[str, int]:
        """(composition, cursor in characters) — always the 國字 text."""
        units = self.decoding.units()
        # in the 按鍵 view: before the character that contains the cursor key
        return self.decoding.text, sum(1 for a, b, _, _ in units if b <= self.cursor)

    def _layer_text(self) -> str:
        """The 注音 or 按鍵 view as one line, with ［ ］ around the cursor."""
        if self.layer == "keys":
            out = []
            for i, k in enumerate(self.keys):
                ch = "␣" if k.char == " " else k.char
                out.append(f"［{ch}］" if i == self.cursor else ch)
            return "".join(out)
        parts = []
        segs = self.decoding.segments
        for a, b, ch, seg_idx in self.decoding.units():
            seg = segs[seg_idx]
            text = seg.readings[seg.bounds.index(a)] if seg.kind is Kind.ZH else ch
            parts.append(f"［{text}］" if a <= self.cursor < b or a == self.cursor else text)
        return " ".join(parts)

    def _correction_hint(self) -> str:
        label = f"【修正·{LAYER_LABEL[self.layer]}】"
        if self.layer == "keys" and self.keys:
            k = self.keys[self.cursor].char
            layout = self.engine.layout
            sym = (layout.symbol(k) or layout.tone(k)) if self.scheme == "zhuyin" else None
            dropped = any(s.kind is Kind.DROP and s.start == self.cursor for s in self.decoding.segments)
            info = f"⌨ {'␣' if k == ' ' else k}" + (f"（{sym or '一聲'}）" if sym is not None else "")
            if dropped:
                info += " 被略過的鍵"
            return f"{label}{self._layer_text()}　{info} · x 刪這個鍵 · v 換檢視 · i 打字"
        if self.layer == "zhuyin":
            return f"{label}{self._layer_text()} · {HELP}"
        return f"{label}{self._unit_info()} · {HELP}"
