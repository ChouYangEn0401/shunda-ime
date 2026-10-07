"""What the on-screen panels show, independent of how they are drawn.

The decode panel (解碼面板) lays the composition out in columns, one per
character on screen, each with three rows:

    按鍵   ji3   e    e/4   dj94   2k7    python
    注音   ㄨㄛˇ  略過  ㄍㄥˋ  ㄎㄨㄞˋ  ㄉㄜ˙↺  英文
    國字   我          更    快     的     python

so it is visible which keys became what, which were skipped as strays (e),
which were typed out of order and read in the right order (2k7 -> ㄉㄜ˙),
and which characters the user picked themselves. The engine builds this
model; the frontend (smartime.ui) only draws it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import bopomofo
from .decoder import CANGJIE_RADICALS, Kind

# Short labels for the reading row of non-Chinese columns.
KIND_LABEL = {
    Kind.EN: "英文", Kind.NUM: "數字", Kind.PUNCT: "標點", Kind.SPACE: "空白",
    Kind.LITERAL: "原樣", Kind.DROP: "略過",
}


@dataclass
class Column:
    keys: str  # the keys behind it, as typed (space shown as ␣)
    reading: str  # zhuyin of the syllable, or a short label (英文, 略過 …)
    text: str  # what is on screen ("" for a skipped key, "…" while unfinished)
    role: str  # zh | en | num | punct | space | literal | pending | drop
    word: int  # index of the word (decoder segment) it belongs to
    start: int  # key span [start, end)
    end: int
    reordered: bool = False  # keys typed out of order, read in the canonical order
    abbreviated: bool = False  # 瘋狂模式: only the start of the syllable was typed
    chosen: bool = False  # picked by the user (candidate window, j/k, Tab)
    memory: str = ""  # from my dictionary: its category, or 學過


@dataclass
class DecodePanel:
    columns: list[Column]
    caret: int  # typing: the caret sits before columns[caret] (len = at the end)
    mode: str = "typing"  # typing | correcting
    layer: str = "text"  # correcting: text | zhuyin | keys (which row the cursor walks)
    focus: int | None = None  # correcting: the column under the cursor
    focus_key: int | None = None  # correcting, 按鍵 view: the key inside columns[focus].keys
    title: str = ""
    help: str = ""
    notice: str = ""
    armed: bool = False  # D pressed once: the next D clears everything


@dataclass
class CandidateItem:
    text: str
    note: str = ""  # category, 學過, 原始按鍵, reading …
    group: str = ""  # see session.GROUP_ORDER
    label: str = ""  # selection key ("1".."9") in the column the selection is in, else ""


@dataclass
class CandidatePanel:
    items: list[CandidateItem]  # after the filter
    index: int  # selected item (into items)
    page_size: int
    columns: int = 1  # pages shown side by side (multi-column mode)
    first_page: int = 0  # leftmost page shown
    pages: int = 1
    title: str = ""  # what is being chosen (context with ［ ］, or the list's name)
    chips: list[str] = field(default_factory=list)  # Tab cycles these: groups, or palette categories
    chip: str = ""  # the active one
    multi: bool = False
    palette: bool = False
    layout: str = "list"  # list | grid (the symbol categories)
    snippet: bool = False  # the ;; list (letters filter it)
    preview: str = ""  # the selected 片語's whole text
    notice: str = ""  # one-off feedback, shown in place of the title


@dataclass
class HintPanel:
    """The thin strip right under the text: what the half-typed keys will
    become, what ``Tab`` would take, and one-off feedback.

    PIME's own hint box is a Windows 95 tooltip (pale yellow, 3D border,
    system font) and it is destroyed and rebuilt on every change, so it
    blinks on every keystroke. We draw this instead and keep PIME's window
    alive, empty and invisible, only as the anchor that tells us where the
    caret is (see smartime.ui.overlay).
    """

    reading: str = ""  # the unfinished syllable: ㄊㄧㄢ, or 倉頡 radicals 竹手戈
    becomes: str = ""  # 倉頡: the character that code would give
    dropped: str = ""  # keys just typed that were skipped as strays
    info: str = ""  # cursor moved back: 今天［針］對　ㄓㄣ ⌨ 5p
    suggestion: str = ""  # what Tab takes
    others: list[str] = field(default_factory=list)  # further continuations
    more: bool = False  # there are more than these; Shift+Tab lists them all
    notice: str = ""  # one-off feedback ("記住了「…」")
    composing: bool = False  # text is still in the composition (not committed yet)

    def __bool__(self) -> bool:
        return bool(self.reading or self.dropped or self.info or self.suggestion or self.notice
                    or self.composing)


@dataclass
class SmartPanel:
    """超智慧推薦 (experimental): [(number in the Shift+Tab list, text)]."""

    chains: list[tuple[str, str]]
    fixes: list[tuple[str, str, str]]  # (number, what is there now, the other word)
    stale: bool = False


def smart_panel(session) -> SmartPanel | None:
    smart = session.smart
    if smart is None or (not smart.chains and not smart.fixes):
        return None
    n = 0
    chains, fixes = [], []
    for s in smart.chains:
        n += 1
        chains.append(("" if smart.stale else str(n), s.text))
    for f in smart.fixes:
        n += 1
        fixes.append(("" if smart.stale else str(n), f.annotation, f.text))
    return SmartPanel(chains, fixes, smart.stale)


def candidate_panel(session) -> CandidatePanel | None:
    """The candidate window as a panel (grouped, coloured by the frontend)."""
    cand = session.cand
    if cand is None:
        return None
    shown = cand.shown
    page = cand.page
    from .symbols import LIST_TABS, TABS

    tab = TABS[cand.palette % len(TABS)] if cand.palette is not None else ""
    grid = cand.palette is not None and tab not in LIST_TABS
    items = [CandidateItem(c.text, c.annotation if c.annotation != c.group and not grid else "",
                           c.group, str(i % cand.page_size + 1) if i // cand.page_size == page else "")
             for i, c in enumerate(shown)]
    panel = CandidatePanel(items, cand.index, cand.page_size, cand.columns, cand.first_page, cand.pages,
                           multi=cand.multi)
    if shown:
        panel.preview = cand.current.preview
    if cand.palette is not None:
        panel.palette = True
        panel.layout = "grid" if grid else "list"
        panel.chips = list(TABS)
        panel.chip = tab
        panel.title = f"符號 · {tab}"
    elif cand.snippet_at is not None:
        panel.snippet = True
        panel.title = f"片語 · 關鍵字：{cand.query}" if cand.query else "片語 · 打關鍵字篩選"
    else:
        groups = cand.groups()
        if len(groups) > 1:
            panel.chips = ["全部"] + groups
            panel.chip = cand.filter or "全部"
        panel.title = cand.title or _candidate_title(session)
    return panel


def _candidate_title(session) -> str:
    """What is being changed: 今天［針］對　ㄓㄣ, or ［mvp］ for a word."""
    t = session._target_unit()
    if t is None:
        return ""
    a, _, _, seg_idx = session.decoding.units()[t]
    seg = session.decoding.segments[seg_idx]
    if seg.kind is Kind.ZH:
        return f"{session._unit_context(t)}　{seg.readings[seg.bounds.index(a)]}"
    label = KIND_LABEL.get(seg.kind, "")
    text = seg.text.replace(" ", "␣")
    return f"［{text}］{label}"


def _display_key(ch: str) -> str:
    return "␣" if ch == " " else ch


def decode_panel(session) -> DecodePanel:
    """Build the decode panel from a Session's current state."""
    dec = session.decoding
    keys = session.keys
    layout = session.engine.layout
    scheme = session.scheme
    columns: list[Column] = []
    for w, seg in enumerate(dec.segments):
        raw = "".join(_display_key(k.char) for k in keys[seg.start:seg.end])
        if seg.kind is Kind.ZH:
            memory = session._note(seg.text, "-".join(seg.readings))
            for i, syl in enumerate(seg.readings):
                a, b = seg.bounds[i], seg.bounds[i + 1]
                typed = "".join(k.char for k in keys[a:b])
                reordered = abbreviated = False
                if scheme == "zhuyin":
                    symbols = [layout.symbol(c) or "" for c in typed[:-1]]
                    tone = layout.tone(typed[-1]) if typed else None
                    reordered = tone is not None and bopomofo.compose_strict(symbols, tone) != syl
                    abbreviated = bool(typed) and tone is None  # no tone key: 瘋狂模式 guessed the rest
                columns.append(Column("".join(_display_key(c) for c in typed), syl, seg.text[i], "zh", w, a, b,
                                      reordered=reordered, abbreviated=abbreviated, chosen=seg.pinned,
                                      memory=memory))
        elif seg.kind is Kind.PENDING:
            if scheme == "zhuyin":
                reading = bopomofo.canonical(layout.symbol(c) or "" for c in seg.text) or \
                    layout.symbols_for_keys(seg.text)
            elif scheme == "cangjie":
                reading = "".join(CANGJIE_RADICALS.get(c, c) for c in seg.text)
            else:
                reading = "拼音"
            columns.append(Column(raw, reading, "…", "pending", w, seg.start, seg.end))
        elif seg.kind is Kind.DROP:
            columns.append(Column(raw, KIND_LABEL[Kind.DROP], "", "drop", w, seg.start, seg.end))
        else:
            text = "␣" if seg.kind is Kind.SPACE else seg.text
            memory = session._note(seg.text.lower(), "") if seg.kind is Kind.EN else ""
            columns.append(Column(raw, KIND_LABEL.get(seg.kind, ""), text, seg.kind.value, w, seg.start, seg.end,
                                  chosen=seg.pinned and seg.kind is not Kind.PUNCT, memory=memory))
    cursor = session.cursor
    caret = next((i for i, c in enumerate(columns) if c.start >= cursor and c.role != "drop"), len(columns))
    panel = DecodePanel(columns, caret)
    if session.correcting:
        panel.mode = "correcting"
        panel.armed = session._clear_armed
        panel.layer = session.layer
        visible = [i for i, c in enumerate(columns) if c.role != "drop" or session.layer == "keys"]
        inside = [i for i in visible if columns[i].start <= cursor < columns[i].end]
        after = [i for i in visible if columns[i].start >= cursor]
        panel.focus = inside[0] if inside else after[0] if after else (visible[-1] if visible else None)
        if panel.focus is not None:
            col = columns[panel.focus]
            # the key under the cursor: in the 按鍵 view, and inside an
            # English word (one column, but h/l walk it letter by letter)
            if session.layer == "keys" or (col.role in ("en", "num", "literal") and col.end - col.start > 1):
                panel.focus_key = max(0, min(cursor, col.end - 1) - col.start)
    return panel
