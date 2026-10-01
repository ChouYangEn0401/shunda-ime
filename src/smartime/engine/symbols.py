"""Symbol panel (Ctrl+Alt+, by default): categories of symbols that have no
key of their own. The first category, 常用, puts recently used symbols first.
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
RECENT_MAX = 18


class SymbolPanel:
    """Recently used symbols, persisted per user (recent-symbols.json)."""

    def __init__(self, path: Path | None):
        self.path = path
        self.recent: list[str] = []
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.recent = [s for s in data if isinstance(s, str) and len(s) == 1][:RECENT_MAX]
            except (OSError, ValueError):
                pass

    def category(self, index: int) -> tuple[str, list[str]]:
        name, chars = CATEGORIES[index % len(CATEGORIES)]
        symbols = list(chars)
        if index % len(CATEGORIES) == 0:
            symbols = list(dict.fromkeys(self.recent + symbols))
        return name, symbols

    def used(self, symbol: str) -> None:
        self.recent = [symbol] + [s for s in self.recent if s != symbol]
        del self.recent[RECENT_MAX:]
        if self.path is None:
            return
        try:
            self.path.write_text(json.dumps(self.recent, ensure_ascii=False), encoding="utf-8")
        except OSError:
            log.warning("cannot save recent symbols")
