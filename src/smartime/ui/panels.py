"""Layout and painting of the panels (see smartime.engine.panel for the
models and smartime.ui.theme for what each colour means).

Every panel is drawn in two passes: ``measure`` decides the size from the
model, ``paint`` draws it. Sizes are logical pixels; the canvas scales.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine.panel import CandidatePanel, Column, DecodePanel, HintPanel, SmartPanel
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
                   ("R", "重新判定"), ("v", "檢視"), ("u", "復原"), ("i/Esc", "打字"), ("Enter", "送出"),
                   ("DD", "清除")]


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
              measure_mixed(c, col.reading + ("↺" if col.reordered else "") + ("…" if col.abbreviated else ""),
                            s.reading, s.symbol),
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
    notice_h = 19 * k if p.notice else 0
    room = MAX_WIDTH * k - 2 * PAD_X * k - GUTTER * k - 2 * 14 * k
    anchor = p.focus if p.focus is not None else max(0, p.caret - 1)
    lo, hi = _visible_range(widths, gaps, anchor, room)
    cols_w = sum(widths[lo:hi]) + sum(gaps[lo + 1:hi])
    more_left, more_right = lo > 0, hi < len(p.columns)
    body_w = GUTTER * k + (14 * k if more_left else 0) + cols_w + (14 * k if more_right else 0) + (4 * k)
    width = max(body_w, _help_width(c, s, help_items),
                measure_mixed(c, p.notice, s.help, s.symbol),
                (c.measure("清除整段？", s.title)[0] + 260 * k) if correcting else 0) + 2 * PAD_X * k
    rows_h = (ROW_KEYS + ROW_READING + ROW_TEXT) * k
    height = PAD_Y * k + header_h + rows_h + 6 * k + notice_h + footer_h + PAD_Y * k
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
        chip = "清除整段？" if p.armed else "修正模式"
        bg, fg = (t.drop_soft, t.drop) if p.armed else (t.fix_soft, t.fix)
        cw = c.measure(chip, s.title)[0] + 14 * k
        c.fill(PAD_X * k, y, cw, 19 * k, bg, radius=4 * k)
        c.text(PAD_X * k + 7 * k, y + 2 * k, chip, s.title, fg)
        view = ("再按一次 D 清除（不會送出）· 其他任何鍵取消" if p.armed else
                f"{LAYER_NAME.get(p.layer, '')}檢視 · 字不會送出，i 或 Esc 回到打字")
        c.text(PAD_X * k + cw + 8 * k, y + 3 * k, view, s.help, t.drop if p.armed else t.muted)
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
            # ↺: the keys were typed out of order and read in the right order;
            # …: 瘋狂模式 guessed the rest of the syllable
            label = col.reading + ("↺" if col.reordered else "") + ("…" if col.abbreviated else "")
            font = s.reading_bold if focused and p.layer == "zhuyin" else s.reading
            center_mixed(c, cx, y_read + 2 * k, cw, label, font, s.symbol,
                         t.fix if (col.reordered or col.abbreviated) else t.muted)
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

    # footer: one-off feedback (it used to live in PIME's box), then key help
    fy = top + rows_h + 6 * k
    c.hline(PAD_X * k, width - PAD_X * k, fy - 3 * k, t.border, 1)
    if p.notice:
        draw_mixed(c, PAD_X * k, fy + 1 * k, p.notice, s.help, s.symbol, t.accent)
        fy += notice_h
    _paint_help(c, s, t, PAD_X * k, fy + 1 * k, help_items, width - PAD_X * k)
    out.regions = {"columns": col_x, "visible": (lo, hi)}
    return out


# ======================================================================== candidates
# Group -> theme colour. Your own words and learned ones are green (memory),
# suggestions purple; raw keys faint; the rest neutral. Coloured groups get a
# bar in front of every item, so a whole group can be skipped at a glance.
GROUP_COLOR = {"我的詞庫": "memory", "學過": "memory", "接續": "predict", "片語": "predict",
               "顏文字": "predict", "原始按鍵": "faint", "長句": "predict", "也許是": "fix"}
ROW_H, GROUP_H, LABEL_W = 29, 19, 16
# ← → walk the group chips when there are any, else they turn pages.
CAND_HELP_GROUPS = [("↑↓", "移動"), ("1–9", "選"), ("← →", "分類"), ("PgUp/PgDn", "翻頁"), ("Del", "忘記"),
                    ("Ctrl+D", "加詞")]
CAND_HELP_PAGES = [("↑↓", "移動"), ("1–9", "選"), ("← →", "翻頁"), ("Del", "忘記"), ("Ctrl+D", "加詞")]
PALETTE_HELP = [("↑↓", "移動"), ("1–9", "選這一列"), ("Tab", "換分類"), ("← →", "翻頁"), ("Esc", "關閉")]
GRID_HELP = [("↑↓ ← →", "移動"), ("1–9", "選這一列"), ("Tab", "換分類"), ("Esc", "關閉")]
# Tab walks eleven categories whose contents are nothing like each other in
# size (「，」 next to 「ヽ(✿ﾟ▽ﾟ)ノ」). A window that resizes under the cursor on
# every Tab is exhausting to follow, so the symbol panel keeps one size for
# all of them, grid tabs and list tabs alike.
PALETTE_W = 520
PALETTE_BODY_H = 9 * 29  # nine list rows; the grid fills the same box
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
    width = max(grid_w, min(chips_w, 560 * k), _help_width(c, s, GRID_HELP),
                PALETTE_W * k) + 2 * PAD_X * k
    chip_lines = _chip_lines(c, s, p.chips, width - 2 * PAD_X * k, k)
    title_h = 20 * k
    chips_h = 24 * k * len(chip_lines)
    grid_h = max(len(rows) * CELL_H * k, PALETTE_BODY_H * k)
    height = PAD_Y * k + title_h + chips_h + 6 * k + grid_h + 8 * k + 20 * k + PAD_Y * k
    out = Painted(width, height)
    if not draw:
        return out
    c.fill(0, 0, width, height, t.bg)
    c.stroke(0, 0, width, height, t.border, line=1)
    x0, y = PAD_X * k, PAD_Y * k
    draw_mixed(c, x0, y, p.notice or p.title, s.help, s.symbol, t.accent if p.notice else t.muted)
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
    _paint_help(c, s, t, x0, fy, GRID_HELP, width - PAD_X * k)
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
        CAND_HELP_GROUPS if p.chips else CAND_HELP_PAGES)
    title_w = measure_mixed(c, p.notice or p.title, s.help, s.symbol) + 60 * k
    chips_w = sum(c.measure(ch, s.small)[0] + 18 * k for ch in p.chips)
    width = max(cols_w, _help_width(c, s, help_items), title_w, min(chips_w, 560 * k),
                360 * k if p.preview else 0) + 2 * PAD_X * k
    width = min(width, max(cols_w + 2 * PAD_X * k, 460 * k if p.preview else 420 * k))
    if p.palette:
        # Tab walks eleven categories whose contents are nothing like each
        # other in width (「，」 vs 「ヽ(✿ﾟ▽ﾟ)ノ」). Letting the window resize
        # under the cursor on every Tab is exhausting to follow, so the panel
        # keeps one width for all of them.
        width = max(width, PALETTE_W * k + 2 * PAD_X * k)
    chip_lines = _chip_lines(c, s, p.chips, width - 2 * PAD_X * k, k) if p.chips else []
    preview = wrap(c, p.preview, s.reading, width - 2 * PAD_X * k - 20 * k, PREVIEW_LINES) if p.preview else []
    preview_h = (len(preview) * 20 * k + 30 * k) if preview else 0
    title_h = 20 * k
    chips_h = 24 * k * len(chip_lines)
    body_h = max((sum(GROUP_H * k if kind == "group" else ROW_H * k for kind, _ in rows) for rows in col_rows),
                 default=ROW_H * k)
    if p.palette:
        body_h = max(body_h, PALETTE_BODY_H * k)  # one height too, for the same reason
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
    draw_mixed(c, x0, y, p.notice or p.title, s.help, s.symbol, t.accent if p.notice else t.muted)
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


# ======================================================================== 超智慧推薦
SMART_HELP = [("Shift+Tab", "選"), ("Tab", "接黃框的第一個"), ("標點／Enter", "收起")]


def paint_smart(c: Canvas, t: Theme, p: SmartPanel, size: float = 1.0, draw: bool = True) -> Painted:
    """The experimental suggestion panel: purple (= suggestions), docked
    under the other panel. Numbers are the ones Shift+Tab shows."""
    s = Styles(c, t, size)
    k = size
    rows: list[tuple[str, str, str, str]] = []  # (kind, number, text, extra)
    if p.chains:
        rows.append(("label", "", "接下來", ""))
        rows += [("chain", n, text, "") for n, text in p.chains]
    if p.fixes:
        rows.append(("label", "", "也許是", ""))
        rows += [("fix", n, new, old) for n, old, new in p.fixes]
    widths = [_help_width(c, s, SMART_HELP), c.measure("超智慧推薦 · 實驗", s.title)[0] + 150 * k]
    for kind, n, text, extra in rows:
        if kind == "chain":
            widths.append((LABEL_W + 10) * k + c.measure(text, s.cand)[0])
        elif kind == "fix":
            widths.append((LABEL_W + 10) * k + c.measure(extra, s.reading)[0] + 30 * k + c.measure(text, s.cand)[0])
    width = min(max(widths) + 2 * PAD_X * k, 620 * k)
    body_h = sum(GROUP_H * k if kind == "label" else ROW_H * k for kind, *_ in rows)
    height = PAD_Y * k + 22 * k + body_h + 8 * k + 20 * k + PAD_Y * k
    out = Painted(width, height)
    if not draw:
        return out
    c.fill(0, 0, width, height, t.bg)
    c.stroke(0, 0, width, height, t.predict, line=1.5)
    x0, y = PAD_X * k, PAD_Y * k
    chip = "超智慧推薦 · 實驗"
    cw = c.measure(chip, s.title)[0] + 14 * k
    c.fill(x0, y, cw, 19 * k, t.predict_soft, radius=4 * k)
    c.text(x0 + 7 * k, y + 2 * k, chip, s.title, t.predict)
    if p.stale:
        c.text(x0 + cw + 8 * k, y + 3 * k, "打完這個字後更新", s.help, t.faint)
    y += 22 * k
    for kind, n, text, extra in rows:
        if kind == "label":
            c.text(x0 + 2 * k, y + 2 * k, text, s.small_bold, t.fix if text == "也許是" else t.predict)
            y += GROUP_H * k
            continue
        color = t.faint if p.stale else t.fg
        if n:
            c.text(x0 + 4 * k, y + 6 * k, n, s.num, t.faint)
        tx = x0 + (LABEL_W + 10) * k
        if kind == "chain":
            c.text(tx, y + 2 * k, text, s.cand, color)
        else:
            c.text(tx, y + 6 * k, extra, s.reading, t.faint)
            ax = tx + c.measure(extra, s.reading)[0] + 8 * k
            c.text(ax, y + 6 * k, "→", s.reading, t.fix)
            c.text(ax + 22 * k, y + 2 * k, text, s.cand, color)
        y += ROW_H * k
    fy = y + 8 * k
    c.hline(x0, width - PAD_X * k, fy - 4 * k, t.border, 1)
    _paint_help(c, s, t, x0, fy, SMART_HELP, width - PAD_X * k)
    return out


# ======================================================================== hint
# The strip right under the text while typing: what the half-typed keys will
# become, what Tab would take, and one-off feedback. It replaces PIME's own
# message window — a Windows 95 tooltip (pale yellow, 3D border, system font)
# that PIME destroys and rebuilds on every change, so it blinked on every
# keystroke. One calm surface, and each thing in it has its own place:
#
#     ㄊㄧㄢ        │  天氣 ⇥  其他 · 選項
#     ^ reading        ^ what Tab takes, then the quieter alternatives
#
# A fast typist should be able to ignore the right-hand side completely, so
# the suggestion is muted and only the ⇥ marker carries the accent colour.
HINT_PAD_X, HINT_PAD_Y = 11, 7
HINT_ROW = 22
HINT_MIN_W = 56  # never smaller than PIME's anchor stub, which this covers
GAP_HINT = 16  # between the zones of the strip


def _hint_others(p: HintPanel) -> str:
    """The suggestions after the first, numbered the way the ⇧⇥ list numbers
    them — so "the second one" has a name and a key, instead of being a word
    you can see and cannot take (reported: 「tab 可以 apply 第一個建議，但我不
    知道如何 apply 更後面的內容」)."""
    return "  ".join(f"{i} {text}" for i, text in enumerate(p.others, start=2))


def _hint_suggest_width(c: Canvas, s: Styles, p: HintPanel, k: float) -> float:
    if not p.suggestion:
        return 0.0
    w = measure_mixed(c, p.suggestion + " ⇥", s.reading, s.symbol) + 14 * k
    rest = _hint_others(p)
    if rest:
        w += c.measure(rest, s.small)[0] + 10 * k
    if p.others:
        w += measure_mixed(c, "⇧⇥ 更多", s.small, s.symbol) + 10 * k
    return w


def paint_hint(c: Canvas, t: Theme, p: HintPanel, size: float = 1.0, draw: bool = True) -> Painted:
    s = Styles(c, t, size)
    k = size

    left = p.info or p.reading
    left_font = s.small if p.info else s.reading_bold
    left_w = measure_mixed(c, left, left_font, s.symbol) if left else 0.0
    becomes = f"→ {p.becomes}  ␣" if p.becomes else ""
    becomes_w = measure_mixed(c, becomes, s.small, s.symbol) + 8 * k if becomes else 0.0
    dropped = f"略過 {p.dropped}  ↓" if p.dropped else ""
    drop_w = measure_mixed(c, dropped, s.small, s.symbol) + 10 * k if dropped else 0.0
    suggest_w = _hint_suggest_width(c, s, p, k)

    # Nothing to say but text is still being composed: a dot, so the state
    # is visible in editors that do not underline the composition.
    dot = not (left or dropped or p.suggestion or p.notice) and p.composing
    parts = [w for w in (drop_w, left_w + becomes_w, suggest_w) if w]
    body_w = sum(parts) + GAP_HINT * k * max(0, len(parts) - 1)
    notice_w = measure_mixed(c, p.notice, s.small, s.symbol) if p.notice else 0.0
    if dot:
        width = height = 18 * k
        out = Painted(width, height)
        if draw:
            c.fill(0, 0, width, height, t.bg)
            c.stroke(0, 0, width, height, t.border, line=1)
            c.fill(6 * k, 6 * k, 6 * k, 6 * k, t.accent, radius=3 * k)
        return out
    width = max(body_w, notice_w, HINT_MIN_W * k) + 2 * HINT_PAD_X * k
    rows = (1 if parts else 0) + (1 if p.notice else 0)
    height = max(1, rows) * HINT_ROW * k + 2 * HINT_PAD_Y * k
    out = Painted(width, height)
    if not draw:
        return out

    c.fill(0, 0, width, height, t.bg)
    c.stroke(0, 0, width, height, t.border, line=1)
    x, y = HINT_PAD_X * k, HINT_PAD_Y * k
    if parts:
        if dropped:
            # red, because a key you typed is not on the screen
            c.fill(x, y + 2 * k, drop_w - 2 * k, 18 * k, t.drop_soft, radius=4 * k)
            draw_mixed(c, x + 5 * k, y + 4 * k, dropped, s.small, s.symbol, t.drop)
            x += drop_w + GAP_HINT * k
        if left:
            draw_mixed(c, x, y + (3 if p.info else 1) * k, left, left_font, s.symbol,
                       t.muted if p.info else t.fg)
            x += left_w
            if becomes:
                draw_mixed(c, x + 8 * k, y + 4 * k, becomes, s.small, s.symbol, t.faint)
                x += becomes_w
            x += GAP_HINT * k
        if suggest_w:
            # right-aligned: a fast typist can ignore this side completely,
            # so it keeps its own place instead of shifting with the reading
            x = max(x, width - HINT_PAD_X * k - suggest_w)
            chip_w = measure_mixed(c, p.suggestion + " ⇥", s.reading, s.symbol) + 14 * k
            c.fill(x, y + 1 * k, chip_w, 20 * k, t.accent_soft, radius=5 * k)
            draw_mixed(c, x + 7 * k, y + 1 * k, p.suggestion + " ⇥", s.reading, s.symbol,
                       t.fg, symbol_color=t.accent)
            x += chip_w + 10 * k
            rest = _hint_others(p)
            if rest:
                c.text(x, y + 4 * k, rest, s.small, t.muted)
                x += c.measure(rest, s.small)[0] + 10 * k
            if p.others:
                draw_mixed(c, x, y + 4 * k, "⇧⇥ 更多", s.small, s.symbol, t.faint)
        y += HINT_ROW * k
    if p.notice:
        draw_mixed(c, HINT_PAD_X * k, y + 3 * k, p.notice, s.small, s.symbol, t.muted)
    return out
