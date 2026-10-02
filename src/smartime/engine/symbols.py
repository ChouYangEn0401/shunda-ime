"""Symbol panel (a lone tap of the right Ctrl key): categories of symbols that
have no key of their own, then 片語 (the user's saved texts) and 顏文字. The
first category, 常用, puts recently used symbols first; 顏文字 puts recently
used faces first.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

CATEGORIES: list[tuple[str, str]] = [
    ("常用", "，。、；：？！…—「」『』（）《》〈〉【】“”～"),
    ("括號引號", "「」『』（）《》〈〉【】〔〕｛｝“”‘’〝〞﹁﹂﹃﹄［］"),
    ("希臘字母", "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"),
    ("數學", "＋－×÷＝≠≈≒±∞√∑∏∫∂∆∇≤≥＜＞∈∉⊂⊃∩∪∴∵∀∃°′″‰％"),
    ("箭頭", "←→↑↓↖↗↙↘⇐⇒⇑⇓⇔↔↕↺↻➜"),
    ("單位", "℃℉°㎜㎝㎞㎡㎥㏄㎎㎏㏎㎖㎗㎘μ＄¢£¥€™©®"),
    ("圖形", "○●◎◇◆□■△▲▽▼☆★♀♂✓✔✗✘※§¶†‡•"),
    ("序號", "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ㈠㈡㈢㈣㈤㈥㈦㈧㈨㈩"),
    ("注音", "ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙㄧㄨㄩㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦˊˇˋ˙"),
]
RECENT_MAX = 18  # single symbols in 常用
RECENT_KAOMOJI = 12
# Tabs after the symbol categories; shown as lists, not as the symbol grid.
LIST_TABS = ("片語", "顏文字")
TABS = [name for name, _ in CATEGORIES] + list(LIST_TABS)


class SymbolPanel:
    """Recently used symbols, persisted per user (recent-symbols.json)."""

    def __init__(self, path: Path | None):
        self.path = path
        self.recent: list[str] = []
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.recent = [s for s in data if isinstance(s, str) and 0 < len(s) <= 40][:RECENT_MAX + RECENT_KAOMOJI]
            except (OSError, ValueError):
                pass

    def category(self, index: int) -> tuple[str, list[str]]:
        name, chars = CATEGORIES[index % len(CATEGORIES)]
        symbols = list(chars)
        if index % len(CATEGORIES) == 0:
            symbols = list(dict.fromkeys([s for s in self.recent if len(s) == 1] + symbols))
        return name, symbols

    def kaomoji(self) -> list[tuple[str, str]]:
        """[(face, group)], the recently used ones first (group 最近)."""
        from .kaomoji import flat

        faces = flat()
        known = {k for k, _ in faces}
        recent = [s for s in self.recent if s in known][:RECENT_KAOMOJI]
        return [(k, "最近") for k in recent] + [(k, g) for k, g in faces if k not in recent]

    def used(self, symbol: str) -> None:
        self.recent = [symbol] + [s for s in self.recent if s != symbol]
        singles = [s for s in self.recent if len(s) == 1][:RECENT_MAX]
        longer = [s for s in self.recent if len(s) > 1][:RECENT_KAOMOJI]
        self.recent = [s for s in self.recent if s in singles or s in longer]
        if self.path is None:
            return
        try:
            self.path.write_text(json.dumps(self.recent, ensure_ascii=False), encoding="utf-8")
        except OSError:
            log.warning("cannot save recent symbols")
