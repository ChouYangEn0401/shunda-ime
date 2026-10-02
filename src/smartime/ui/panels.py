"""Layout and painting of the panels (see smartime.engine.panel for the
models and smartime.ui.theme for what each colour means).

Every panel is drawn in two passes: ``measure`` decides the size from the
model, ``paint`` draws it. Sizes are logical pixels; the canvas scales.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine.panel import CandidatePanel, Column, DecodePanel
from .canvas import Canvas
from .theme import Theme

PAD_X, PAD_Y = 12, 9
MAX_WIDTH = 760
GUTTER = 34  # row labels
ROW_KEYS, ROW_READING, ROW_TEXT = 21, 21, 31
WORD_GAP, CHAR_GAP = 9, 2

LAYER_NAME = {"text": "國字", "zhuyin": "注音", "keys": "按鍵"}
TYPING_HELP = [("Esc", "修正模式"), ("Ctrl+Z", "復原"), ("↓", "選字")]
CORRECTING_HELP = [("h l", "移動"), ("j k", "換字"), ("x", "刪"), ("e", "中⇄英"), ("r", "重打"),
                   ("v", "檢視"), ("u", "復原"), ("i/Esc", "打字"), ("Enter", "送出"), ("DD", "清除")]


@dataclass
class Painted:
    width: float
    height: float
    regions: dict = field(default_factory=dict)  # name -> (x, y, w, h), for tests


class Styles:
    """Fonts for one canvas (the scale is the canvas's)."""

    def __init__(self, canvas: Canvas, theme: Theme, size: float = 1.0):
        f = canvas.fonts.get
        ui, mono = theme.font_ui, theme.font_mono
        self.label = f(ui, 11 * size)
        self.help = f(ui, 11.5 * size)
        self.help_key = f(mono, 11 * size, 600)
        self.keys = f(mono, 13.5 * size)
        self.keys_bold = f(mono, 13.5 * size, 700)
        self.keys_strike = f(mono, 13.5 * size, 400, strike=True)
        self.reading = f(ui, 13 * size)
        self.reading_bold = f(ui, 13 * size, 700)
        self.small = f(ui, 11 * size)
        self.small_bold = f(ui, 11 * size, 700)
        self.text = f(ui, 19 * size)
        self.text_bold = f(ui, 19 * size, 700)
        self.title = f(ui, 12 * size, 700)
        self.cand = f(ui, 17 * size)
        self.cand_note = f(ui, 11.5 * size)
        self.num = f(mono, 12 * size)
        # glyphs the text fonts lack (␣ ↺ ⇄): Segoe UI Symbol has them all
        self.symbol = f("Segoe UI Symbol", 12.5 * size)
        self.keys_symbol = f("Segoe UI Symbol", 13 * size)


SYMBOL_CHARS = frozenset("␣↺⇄⇥")


def _runs(text: str):
    """Split text into (chunk, is_symbol) runs."""
    out: list[tuple[str, bool]] = []
    for ch in text:
        sym = ch in SYMBOL_CHARS
        if out and out[-1][1] == sym:
            out[-1] = (out[-1][0] + ch, sym)
        else:
            out.append((ch, sym))
    return out


def measure_mixed(c: Canvas, text: str, font: int, symbol_font: int) -> float:
    return sum(c.measure(chunk, symbol_font if sym else font)[0] for chunk, sym in _runs(text))


def draw_mixed(c: Canvas, x: float, y: float, text: str, font: int, symbol_font: int, color: int,
               symbol_color: int | None = None, symbol_dy: float = 0) -> float:
    """Text with symbol glyphs from another font, on one baseline."""
    base = c.ascent(font)
    for chunk, sym in _runs(text):
        f = symbol_font if sym else font
        dy = (base - c.ascent(f) + symbol_dy) if sym else 0
        c.text(x, y + dy, chunk, f, symbol_color if (sym and symbol_color is not None) else color)
        x += c.measure(chunk, f)[0]
    return x


def center_mixed(c: Canvas, x: float, y: float, width: float, text: str, font: int, symbol_font: int, color: int,
                 symbol_color: int | None = None, symbol_dy: float = 0) -> None:
    tw = measure_mixed(c, text, font, symbol_font)
    draw_mixed(c, x + (width - tw) / 2, y, text, font, symbol_font, color, symbol_color, symbol_dy)


# ======================================================================== decode
def _column_width(c: Canvas, s: Styles, col: Column) -> float:
    widths = [measure_mixed(c, col.keys, s.keys, s.keys_symbol),
              measure_mixed(c, col.reading + ("↺" if col.reordered else ""), s.reading, s.symbol),
              c.measure(col.text, s.text)[0]]
    return max(max(widths) + 10, 24)


def _visible_range(widths: list[float], gaps: list[float], anchor: int, room: float) -> tuple[int, int]:
    """The columns that fit in ``room``, centred on ``anchor``."""
    n = len(widths)
    if not n:
        return 0, 0
    anchor = max(0, min(anchor, n - 1))
    lo, hi = anchor, anchor + 1
    used = widths[anchor]
    while True:
        grew = False
        if hi < n and used + gaps[hi] + widths[hi] <= room:
            used += gaps[hi] + widths[hi]
            hi += 1
            grew = True
        if lo > 0 and used + gaps[lo] + widths[lo - 1] <= room:
            used += gaps[lo] + widths[lo - 1]
            lo -= 1
            grew = True
        if not grew:
            return lo, hi


def _help_width(c: Canvas, s: Styles, items) -> float:
    total = 0.0
    for keys, label in items:
        total += c.measure(keys, s.help_key)[0] + 4 + measure_mixed(c, label, s.help, s.symbol) + 12
    return total - 12 if items else 0.0


def _paint_help(c: Canvas, s: Styles, t: Theme, x: float, y: float, items, max_x: float) -> None:
    for keys, label in items:
        kw = c.measure(keys, s.help_key)[0]
        lw = measure_mixed(c, label, s.help, s.symbol)
        if x + kw + 4 + lw > max_x:
            break
        c.text(x, y + 1, keys, s.help_key, t.fg)
        draw_mixed(c, x + kw + 4, y, label, s.help, s.symbol, t.muted)
        x += kw + 4 + lw + 12


def paint_decode(c: Canvas, t: Theme, p: DecodePanel, size: float = 1.0, draw: bool = True) -> Painted:
    s = Styles(c, t, size)
    k = size
    correcting = p.mode == "correcting"
    widths = [_column_width(c, s, col) for col in p.columns]
    gaps = [0.0] + [(WORD_GAP if p.columns[i].word != p.columns[i - 1].word else CHAR_GAP) * k
                    for i in range(1, len(p.columns))]
    help_items = CORRECTING_HELP if correcting else TYPING_HELP
    header_h = 24 * k if correcting else 0
    footer_h = 20 * k
    room = MAX_WIDTH * k - 2 * PAD_X * k - GUTTER * k - 2 * 14 * k
    anchor = p.focus if p.focus is not None else max(0, p.caret - 1)
    lo, hi = _visible_range(widths, gaps, anchor, room)
    cols_w = sum(widths[lo:hi]) + sum(gaps[lo + 1:hi])
    more_left, more_right = lo > 0, hi < len(p.columns)
    body_w = GUTTER * k + (14 * k if more_left else 0) + cols_w + (14 * k if more_right else 0) + (4 * k)
    width = max(body_w, _help_width(c, s, help_items),
                (c.measure("修正模式", s.title)[0] + 160 * k) if correcting else 0) + 2 * PAD_X * k
    rows_h = (ROW_KEYS + ROW_READING + ROW_TEXT) * k
    height = PAD_Y * k + header_h + rows_h + 6 * k + footer_h + PAD_Y * k
    out = Painted(width, height)
    if not draw:
        return out

    # frame: amber and thicker in correction mode, so the mode is never in doubt
    c.fill(0, 0, width, height, t.bg)
    if correcting:
        c.stroke(0, 0, width, height, t.fix, radius=0, line=2)
    else:
        c.stroke(0, 0, width, height, t.border, radius=0, line=1)

    y = PAD_Y * k
    if correcting:
        chip = "修正模式"
        cw = c.measure(chip, s.title)[0] + 14 * k
        c.fill(PAD_X * k, y, cw, 19 * k, t.fix_soft, radius=4 * k)
        c.text(PAD_X * k + 7 * k, y + 2 * k, chip, s.title, t.fix)
        view = f"{LAYER_NAME.get(p.layer, '')}檢視 · 字不會送出，i 或 Esc 回到打字"
        c.text(PAD_X * k + cw + 8 * k, y + 3 * k, view, s.help, t.muted)
        y += header_h

    top = y
    x0 = PAD_X * k
    labels = (("按鍵", ROW_KEYS), ("注音", ROW_READING), ("國字", ROW_TEXT))
    ly = top
    for name, h in labels:
        hl = correcting and ((name == "按鍵" and p.layer == "keys") or (name == "注音" and p.layer == "zhuyin")
                             or (name == "國字" and p.layer == "text"))
        c.text(x0, ly + (h * k - 15 * k) / 2, name, s.small_bold if hl else s.label, t.fix if hl else t.faint)
        ly += h * k
    x = x0 + GUTTER * k
    if more_left:
        c.text(x, top + ROW_KEYS * k + 2 * k, "…", s.reading, t.faint)
        x += 14 * k
    col_x: dict[int, float] = {}
    for i in range(lo, hi):
        if i > lo:
            x += gaps[i]
        col_x[i] = x
        x += widths[i]
    end_x = x

    # focus column (correction mode) behind everything
    if correcting and p.focus is not None and p.focus in col_x:
        fx = col_x[p.focus]
        c.fill(fx - 2 * k, top, widths[p.focus] + 4 * k, rows_h, t.accent_soft, radius=5 * k)

    # word brackets under multi-character words
    words: dict[int, list[int]] = {}
    for i in range(lo, hi):
        words.setdefault(p.columns[i].word, []).append(i)
    for idxs in words.values():
        if len(idxs) > 1 and p.columns[idxs[0]].role == "zh":
            a, b = col_x[idxs[0]], col_x[idxs[-1]] + widths[idxs[-1]]
            c.hline(a + 3 * k, b - 3 * k, top + rows_h - 3 * k, t.border, 1)

    for i in range(lo, hi):
        col = p.columns[i]
        cx, cw = col_x[i], widths[i]
        focused = correcting and p.focus == i
        y_keys, y_read, y_text = top, top + ROW_KEYS * k, top + (ROW_KEYS + ROW_READING) * k
        # --- keys row
        if p.focus_key is not None and focused:
            # one key under the cursor (按鍵 view, or a letter inside a word)
            if col.role == "drop":
                c.fill(cx + 1 * k, y_keys + 2 * k, cw - 2 * k, ROW_KEYS * k - 4 * k, t.drop_soft, radius=3 * k)
            kx = cx + (cw - measure_mixed(c, col.keys, s.keys, s.keys_symbol)) / 2
            for j, ch in enumerate(col.keys):
                f = s.keys_symbol if ch in SYMBOL_CHARS else s.keys
                chw = c.measure(ch, f)[0]
                dy = (c.ascent(s.keys) - c.ascent(f)) if ch in SYMBOL_CHARS else 0
                if j == p.focus_key:
                    c.fill(kx - 2 * k, y_keys + 2 * k, chw + 4 * k, ROW_KEYS * k - 4 * k, t.accent, radius=3 * k)
                    c.text(kx, y_keys + 2 * k + dy, ch, s.keys_symbol if ch in SYMBOL_CHARS else s.keys_bold,
                           t.on_accent)
                else:
                    c.text(kx, y_keys + 2 * k + dy, ch, f, t.drop if col.role == "drop" else t.fg)
                kx += chw
        elif col.role == "drop":
            c.fill(cx + 1 * k, y_keys + 2 * k, cw - 2 * k, ROW_KEYS * k - 4 * k, t.drop_soft, radius=3 * k)
            center_mixed(c, cx, y_keys + 2 * k, cw, col.keys, s.keys_strike, s.keys_symbol, t.drop)
        else:
            center_mixed(c, cx, y_keys + 2 * k, cw, col.keys, s.keys_bold if focused and p.layer == "keys" else s.keys,
                         s.keys_symbol, t.muted if col.role == "space" else t.fg)
        # --- reading row
        if col.role == "drop":
            c.text_center(cx, y_read + 3 * k, cw, col.reading, s.small, t.drop)
        elif col.role == "pending":
            c.text_center(cx, y_read + 2 * k, cw, col.reading, s.reading_bold, t.accent)
        elif col.role == "zh":
            # ↺: the keys were typed out of order and read in the right order
            label = col.reading + ("↺" if col.reordered else "")
            font = s.reading_bold if focused and p.layer == "zhuyin" else s.reading
            center_mixed(c, cx, y_read + 2 * k, cw, label, font, s.symbol, t.fix if col.reordered else t.muted)
        else:
            c.text_center(cx, y_read + 3 * k, cw, col.reading, s.small, t.faint)
        # --- text row
        if col.role == "pending":
            c.text_center(cx, y_text + 1 * k, cw, col.text, s.text, t.faint)
        elif col.role == "space":
            c.text_center(cx, y_text + 1 * k, cw, col.text, s.text, t.faint)
        elif col.role != "drop":
            c.text_center(cx, y_text + 1 * k, cw, col.text, s.text_bold if focused and p.layer == "text" else s.text,
                          t.fg)
        if col.chosen:  # picked by the user
            c.hline(cx + 5 * k, cx + cw - 5 * k, y_text + ROW_TEXT * k - 6 * k, t.accent, 2)
        if col.memory:  # from my dictionary / learned
            c.fill(cx + cw - 7 * k, y_text + 4 * k, 5 * k, 5 * k, t.memory, radius=2.5 * k)

    # typing caret
    if not correcting:
        if p.caret in col_x:
            cxp = col_x[p.caret] - (gaps[p.caret] / 2 if p.caret > lo else 1 * k)
        elif p.caret >= hi:
            cxp = end_x + 2 * k
        else:
            cxp = None
        if cxp is not None:
            c.fill(cxp - 1 * k, top + 2 * k, 2 * k, rows_h - 4 * k, t.accent)
    if more_right:
        c.text(end_x + 4 * k, top + ROW_KEYS * k + 2 * k, "…", s.reading, t.faint)

    # footer: key help
    fy = top + rows_h + 6 * k
    c.hline(PAD_X * k, width - PAD_X * k, fy - 3 * k, t.border, 1)
    _paint_help(c, s, t, PAD_X * k, fy + 1 * k, help_items, width - PAD_X * k)
    out.regions = {"columns": col_x, "visible": (lo, hi)}
    return out


# ======================================================================== candidates
# Group -> theme colour. Your own words and learned ones are green (memory),
# suggestions purple; raw keys faint; the rest neutral. Coloured groups get a
# bar in front of every item, so a whole group can be skipped at a glance.
GROUP_COLOR = {"我的詞庫": "memory", "學過": "memory", "接續": "predict", "片語": "predict",
               "顏文字": "predict", "原始按鍵": "faint"}
ROW_H, GROUP_H, LABEL_W = 29, 19, 16
CAND_HELP = [("↑↓", "移動"), ("1–9", "選"), ("Tab", "分類"), ("→", "更多"), ("Del", "忘記"), ("Ctrl+D", "加詞")]
CAND_HELP_SINGLE = [("↑↓", "移動"), ("1–9", "選"), ("Tab", "分類"), ("← →", "翻頁"), ("Del", "忘記"),
                    ("Ctrl+D", "加詞")]
PALETTE_HELP = [("1–9", "選"), ("Tab", "換分類"), ("→", "更多"), ("Esc", "關閉")]
SNIPPET_HELP = [("字母", "篩選"), ("↑↓", "移動"), ("1–9", "選"), ("Enter", "打出"), ("Esc", "關閉（保留 ;;）")]
PREVIEW_LINES = 8


def wrap(c: Canvas, text: str, font: int, width: float, max_lines: int) -> list[str]:
    """Break text into lines that fit ``width`` (character by character:
    Chinese has no spaces), at most ``max_lines`` (the last ends with …)."""
    lines: list[str] = []
    for para in text[:600].split("\n"):
        line = ""
        for ch in para:
            if line and c.measure(line + ch, font)[0] > width:
                lines.append(line)
                line = ch
            else:
                line += ch
        lines.append(line)
        if len(lines) > max_lines:
            break
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _group_color(t: Theme, group: str) -> int | None:
    name = GROUP_COLOR.get(group)
    return getattr(t, name) if name else None


def _columns(p: CandidatePanel):
    """[(page, [(index, item), ...]), ...] for the pages shown."""
    out = []
    for page in range(p.first_page, min(p.first_page + p.columns, p.pages)):
        start = page * p.page_size
        out.append((page, list(enumerate(p.items[start:start + p.page_size], start))))
    return out


def _column_rows(rows):
    """Insert a group header wherever the group changes inside a column."""
    out, last = [], None
    for idx, item in rows:
        if item.group != last and item.group:
            out.append(("group", item.group))
            last = item.group
        out.append(("item", (idx, item)))
    return out


CELL_W, CELL_H = 38, 38


def paint_palette(c: Canvas, t: Theme, p: CandidatePanel, size: float = 1.0, draw: bool = True) -> Painted:
    """The symbol panel: a grid, one page (1–9) per row, the category chips
    above. Numbers are shown on the row the selection is in."""
    s = Styles(c, t, size)
    k = size
    rows = _columns(p)  # pages shown = rows here
    grid_w = p.page_size * CELL_W * k
    chips_w = sum(c.measure(ch, s.small)[0] + 18 * k for ch in p.chips)
    width = max(grid_w, min(chips_w, 560 * k), _help_width(c, s, PALETTE_HELP)) + 2 * PAD_X * k
    chip_lines = _chip_lines(c, s, p.chips, width - 2 * PAD_X * k, k)
    title_h = 20 * k
    chips_h = 24 * k * len(chip_lines)
    grid_h = len(rows) * CELL_H * k
    height = PAD_Y * k + title_h + chips_h + 6 * k + grid_h + 8 * k + 20 * k + PAD_Y * k
    out = Painted(width, height)
    if not draw:
        return out
    c.fill(0, 0, width, height, t.bg)
    c.stroke(0, 0, width, height, t.border, line=1)
    x0, y = PAD_X * k, PAD_Y * k
    c.text(x0, y, f"符號 · {p.chip}", s.help, t.muted)
    pages = f"{p.first_page + 1}–{p.first_page + len(rows)}/{p.pages}" if len(rows) > 1 else f"1/{p.pages}"
    if p.pages > 1:
        c.text(width - PAD_X * k - c.measure(pages, s.num)[0], y + 1 * k, pages, s.num, t.faint)
    y += title_h
    for line in chip_lines:
        _paint_chips(c, s, t, x0, y, line, p.chip, k)
        y += 24 * k
    c.hline(x0, width - PAD_X * k, y + 2 * k, t.border, 1)
    y += 6 * k
    for r, (page, items) in enumerate(rows):
        cy = y + r * CELL_H * k
        for col, (idx, item) in enumerate(items):
            cx = x0 + col * CELL_W * k
            selected = idx == p.index
            if selected:
                c.fill(cx + 1 * k, cy + 1 * k, CELL_W * k - 2 * k, CELL_H * k - 2 * k, t.accent, radius=5 * k)
            if item.label:
                c.text(cx + 3 * k, cy + 1 * k, item.label, s.label, t.on_accent if selected else t.faint)
            c.text_center(cx, cy + 9 * k, CELL_W * k, item.text, s.cand, t.on_accent if selected else t.fg)
    fy = y + grid_h + 8 * k
    c.hline(x0, width - PAD_X * k, fy - 4 * k, t.border, 1)
    _paint_help(c, s, t, x0, fy, PALETTE_HELP, width - PAD_X * k)
    return out


def _chip_lines(c: Canvas, s: Styles, chips: list[str], room: float, k: float) -> list[list[str]]:
    lines: list[list[str]] = [[]]
    used = 0.0
    for ch in chips:
        cw = c.measure(ch, s.small)[0] + 18 * k
        if lines[-1] and used + cw > room:
            lines.append([])
            used = 0.0
        lines[-1].append(ch)
        used += cw
    return [line for line in lines if line]


def _paint_chips(c: Canvas, s: Styles, t: Theme, x: float, y: float, chips: list[str], active: str,
                 k: float) -> None:
    for ch in chips:
        cw = c.measure(ch, s.small)[0] + 14 * k
        color = _group_color(t, ch)
        if ch == active:
            c.fill(x, y + 1 * k, cw, 19 * k, t.accent_soft, radius=9 * k)
            c.text(x + 7 * k, y + 3 * k, ch, s.small_bold, t.accent)
        else:
            c.text(x + 7 * k, y + 3 * k, ch, s.small, color if color is not None else t.muted)
        x += cw + 4 * k


def paint_candidates(c: Canvas, t: Theme, p: CandidatePanel, size: float = 1.0, draw: bool = True) -> Painted:
    if p.palette and p.layout == "grid":
        return paint_palette(c, t, p, size, draw)
    s = Styles(c, t, size)
    k = size
    cols = _columns(p)
    col_rows = [_column_rows(rows) for _, rows in cols]
    # widths
    col_w = []
    for rows in col_rows:
        w = 96 * k
        for kind, val in rows:
            if kind == "group":
                w = max(w, c.measure(val, s.small_bold)[0] + 16 * k)
            else:
                _, item = val
                tw = c.measure(item.text, s.cand)[0]
                nw = c.measure(item.note, s.cand_note)[0] if item.note else 0
                w = max(w, (LABEL_W + 10) * k + tw + (10 * k + nw if nw else 0) + 14 * k)
        col_w.append(w)
    gap = 10 * k
    cols_w = sum(col_w) + gap * max(0, len(col_w) - 1)
    help_items = SNIPPET_HELP if p.snippet else PALETTE_HELP if p.palette else (
        CAND_HELP if p.multi else CAND_HELP_SINGLE)
    title_w = c.measure(p.title, s.help)[0] + 60 * k
    chips_w = sum(c.measure(ch, s.small)[0] + 18 * k for ch in p.chips)
    width = max(cols_w, _help_width(c, s, help_items), title_w, min(chips_w, 560 * k),
                360 * k if p.preview else 0) + 2 * PAD_X * k
    width = min(width, max(cols_w + 2 * PAD_X * k, 460 * k if p.preview else 420 * k))
    chip_lines = _chip_lines(c, s, p.chips, width - 2 * PAD_X * k, k) if p.chips else []
    preview = wrap(c, p.preview, s.reading, width - 2 * PAD_X * k - 20 * k, PREVIEW_LINES) if p.preview else []
    preview_h = (len(preview) * 20 * k + 30 * k) if preview else 0
    title_h = 20 * k
    chips_h = 24 * k * len(chip_lines)
    body_h = max((sum(GROUP_H * k if kind == "group" else ROW_H * k for kind, _ in rows) for rows in col_rows),
                 default=ROW_H * k)
    footer_h = 20 * k
    height = PAD_Y * k + title_h + chips_h + 4 * k + body_h + preview_h + 8 * k + footer_h + PAD_Y * k
    out = Painted(width, height)
    if not draw:
        return out

    c.fill(0, 0, width, height, t.bg)
    c.stroke(0, 0, width, height, t.border, line=1)
    x0, y = PAD_X * k, PAD_Y * k
    # title: what is being chosen, and where we are
    pages = f"{p.first_page + 1}–{p.first_page + len(cols)}/{p.pages}" if len(cols) > 1 else f"{p.index // p.page_size + 1}/{p.pages}"
    c.text(x0, y, p.title, s.help, t.muted)
    pw = c.measure(pages, s.num)[0]
    if p.pages > 1:
        c.text(width - PAD_X * k - pw, y + 1 * k, pages, s.num, t.faint)
    y += title_h
    # Tab chips: the groups (or the symbol panel's tabs); the active one filled
    for line in chip_lines:
        _paint_chips(c, s, t, x0, y, line, p.chip, k)
        y += 24 * k
    c.hline(x0, width - PAD_X * k, y + 1 * k, t.border, 1)
    y += 4 * k
    # columns
    x = x0
    for (page, _), rows, cw in zip(cols, col_rows, col_w):
        ry = y + 2 * k
        for kind, val in rows:
            if kind == "group":
                color = _group_color(t, val)
                c.text(x + 2 * k, ry + 2 * k, val, s.small_bold, color if color is not None else t.faint)
                ry += GROUP_H * k
                continue
            idx, item = val
            selected = idx == p.index
            color = _group_color(t, item.group)
            if selected:
                c.fill(x, ry, cw, ROW_H * k - 2 * k, t.accent, radius=5 * k)
            elif color is not None:
                c.fill(x, ry + 4 * k, 3 * k, ROW_H * k - 10 * k, color, radius=1.5 * k)
            fg = t.on_accent if selected else t.fg
            if item.label:
                c.text(x + 7 * k, ry + 6 * k, item.label, s.num, t.on_accent if selected else t.faint)
            tx = x + (LABEL_W + 10) * k
            c.text(tx, ry + 2 * k, item.text, s.cand, fg)
            if item.note:
                nx = tx + c.measure(item.text, s.cand)[0] + 10 * k
                note_color = t.on_accent if selected else (color if color is not None else t.muted)
                c.text(nx, ry + 7 * k, item.note, s.cand_note, note_color)
            ry += ROW_H * k
        x += cw + gap
        if x < x0 + cols_w:
            c.vline(x - gap / 2, y + 2 * k, y + body_h, t.border, 1)
    if preview:
        # the selected 片語 as it will be typed
        py = y + body_h + 6 * k
        c.fill(x0, py, width - 2 * PAD_X * k, preview_h - 8 * k, t.surface, radius=6 * k)
        c.text(x0 + 10 * k, py + 4 * k, "預覽 · Enter 打出", s.small, t.faint)
        ly = py + 22 * k
        for line in preview:
            c.text(x0 + 10 * k, ly, line, s.reading, t.fg)
            ly += 20 * k
    fy = y + body_h + preview_h + 8 * k
    c.hline(x0, width - PAD_X * k, fy - 4 * k, t.border, 1)
    _paint_help(c, s, t, x0, fy, help_items, width - PAD_X * k)
    return out
