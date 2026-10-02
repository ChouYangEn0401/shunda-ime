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


@dataclass
class CandidateItem:
    text: str
    note: str = ""  # category, 學過, 原始按鍵, reading …
    group: str = ""  # see CandidatePanel.GROUPS
    label: str = ""  # selection key shown in front ("1".."9"), "" when not on the current page


@dataclass
class CandidatePanel:
    items: list[CandidateItem]
    index: int  # selected item (into items)
    page_size: int
    columns: int = 1  # pages shown side by side (→ opens more, ← at the first closes)
    first_page: int = 0  # leftmost page shown
    title: str = ""
    filter: str = ""  # "" = all groups, else one group name
    filters: list[str] = field(default_factory=list)  # groups present (for the Tab filter chips)
    help: str = ""

    # Group names, in display order, with the role the frontend colours.
    GROUPS = ("我的詞庫", "學過", "詞庫", "其他讀法", "原始按鍵", "符號", "接續", "片語", "顏文字")


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
                reordered = False
                if scheme == "zhuyin":
                    symbols = [layout.symbol(c) or "" for c in typed[:-1]]
                    tone = layout.tone(typed[-1]) if typed else None
                    reordered = tone is not None and bopomofo.compose_strict(symbols, tone) != syl
                columns.append(Column("".join(_display_key(c) for c in typed), syl, seg.text[i], "zh", w, a, b,
                                      reordered=reordered, chosen=seg.pinned, memory=memory))
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
