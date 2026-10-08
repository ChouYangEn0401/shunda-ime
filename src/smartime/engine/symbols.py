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

# Picking this types a line break. Shift+Enter normally does it, but some
# remote-desktop clients never deliver the Shift, and then there is no other
# way to break a line from inside the input method.
NEWLINE_SYMBOL = "⏎"

CATEGORIES: list[tuple[str, str]] = [
    ("常用", "，。、；：？！…—「」『』（）《》〈〉【】“”～⏎"),
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
# The searchable catalogue. Called 搜尋符號 at first; renamed because that
# described the mechanism, not the thing — people look for "emoji".
EMOJI_TAB = "emoji"
LIST_TABS = ("片語", "顏文字", "我的符號", EMOJI_TAB)
TABS = [name for name, _ in CATEGORIES] + list(LIST_TABS)

# ------------------------------------------------------------- emoji
# A bigger, keyword-searchable catalogue — stars, hearts, checkmarks,
# weather, zodiac, warning signs, religious/cultural marks, card suits,
# pointing hands, simple (non-colour) faces, ornamental dividers.
#
# Deliberately only characters in the Unicode BMP (U+0000–U+FFFF), the same
# range the 數學/箭頭/圖形/序號 categories above already draw from. Full-colour
# emoji (🎉😀) live in the Supplementary Multilingual Plane and need a
# colour-font renderer (DirectWrite, not plain GDI ExtTextOutW); this
# backend draws everything through GDI, so they are out of scope for now
# rather than silently shown as tofu boxes. Everything below is a real,
# monochrome Unicode character that Segoe UI Symbol already carries a glyph
# for — the same font the rest of the symbol panel already draws with.
#
# (symbol, category label, extra search tags — zh and en, lowercase)
EMOJI_SYMBOLS: list[tuple[str, str, tuple[str, ...]]] = [
    # 星星・亮光
    ("★", "星星", ("star", "實心星")), ("☆", "星星", ("star", "空心星")),
    ("✦", "星星", ("star", "sparkle")), ("✧", "星星", ("star", "sparkle", "空心")),
    ("✩", "星星", ("star",)), ("✪", "星星", ("star", "圈")), ("✫", "星星", ("star",)),
    ("✬", "星星", ("star",)), ("✭", "星星", ("star",)), ("✮", "星星", ("star",)),
    ("✯", "星星", ("star",)), ("✰", "星星", ("star", "shooting", "流星")),
    ("⁂", "星星", ("asterism", "分段")),
    # 愛心
    ("♥", "愛心", ("heart", "love", "實心")), ("❤", "愛心", ("heart", "love")),
    ("❥", "愛心", ("heart", "love")), ("❣", "愛心", ("heart", "love", "驚嘆")),
    ("♡", "愛心", ("heart", "love", "空心")),
    # 勾叉・核取
    ("✓", "勾叉", ("check", "勾", "對")), ("✔", "勾叉", ("check", "勾", "對")),
    ("✗", "勾叉", ("cross", "叉", "錯")), ("✘", "勾叉", ("cross", "叉", "錯")),
    ("☑", "勾叉", ("checkbox", "勾選框")), ("☐", "勾叉", ("checkbox", "空白框")),
    ("☒", "勾叉", ("checkbox", "打叉框")),
    # 天氣
    ("☀", "天氣", ("sun", "太陽", "晴天")), ("☁", "天氣", ("cloud", "雲", "陰天")),
    ("☂", "天氣", ("umbrella", "雨傘")), ("☔", "天氣", ("rain", "下雨", "雨傘")),
    ("☃", "天氣", ("snowman", "雪人")), ("❄", "天氣", ("snow", "雪花")),
    ("☄", "天氣", ("comet", "彗星")), ("⚡", "天氣", ("lightning", "閃電", "高壓")),
    ("☽", "天氣", ("moon", "月亮", "上弦月")), ("☾", "天氣", ("moon", "月亮", "下弦月")),
    # 星座
    ("♈", "星座", ("aries", "牡羊座")), ("♉", "星座", ("taurus", "金牛座")),
    ("♊", "星座", ("gemini", "雙子座")), ("♋", "星座", ("cancer", "巨蟹座")),
    ("♌", "星座", ("leo", "獅子座")), ("♍", "星座", ("virgo", "處女座")),
    ("♎", "星座", ("libra", "天秤座")), ("♏", "星座", ("scorpio", "天蠍座")),
    ("♐", "星座", ("sagittarius", "射手座")), ("♑", "星座", ("capricorn", "摩羯座")),
    ("♒", "星座", ("aquarius", "水瓶座")), ("♓", "星座", ("pisces", "雙魚座")),
    # 音樂
    ("♩", "音樂", ("music", "音符")), ("♪", "音樂", ("music", "音符")),
    ("♫", "音樂", ("music", "音符", "連音")), ("♬", "音樂", ("music", "音符", "連音")),
    ("♭", "音樂", ("music", "降記號")), ("♮", "音樂", ("music", "還原記號")),
    ("♯", "音樂", ("music", "升記號")),
    # 警示・標示
    ("⚠", "警示", ("warning", "警告")), ("⛔", "警示", ("no entry", "禁止")),
    ("☢", "警示", ("radioactive", "輻射")), ("☣", "警示", ("biohazard", "生化")),
    ("♻", "警示", ("recycle", "回收")), ("☠", "警示", ("skull", "骷髏", "危險")),
    ("⚑", "警示", ("flag", "旗標")), ("⚐", "警示", ("flag", "旗標", "空心")),
    # 宗教文化
    ("☯", "宗教文化", ("yin yang", "太極", "陰陽")), ("☦", "宗教文化", ("cross", "東正教")),
    ("✝", "宗教文化", ("cross", "十字架")), ("☪", "宗教文化", ("crescent", "星月")),
    ("✡", "宗教文化", ("star of david", "六芒星")), ("♁", "宗教文化", ("earth", "地球")),
    # 撲克牌花色
    ("♠", "花色", ("spade", "黑桃")), ("♣", "花色", ("club", "梅花")),
    ("♥", "花色", ("heart", "紅心")), ("♦", "花色", ("diamond", "方塊")),
    ("♤", "花色", ("spade", "黑桃", "空心")), ("♧", "花色", ("club", "梅花", "空心")),
    ("♢", "花色", ("diamond", "方塊", "空心")),
    # 手勢方向
    ("☚", "手勢", ("pointing", "手指", "左")), ("☛", "手勢", ("pointing", "手指", "右")),
    ("☜", "手勢", ("pointing", "手指", "左", "空心")), ("☝", "手勢", ("pointing", "手指", "上")),
    ("☞", "手勢", ("pointing", "手指", "右", "空心")), ("☟", "手勢", ("pointing", "手指", "下")),
    # 簡單表情（純黑白符號，不是彩色 emoji）
    ("☺", "表情", ("smile", "笑臉", "開心")), ("☻", "表情", ("smile", "笑臉", "實心")),
    ("☹", "表情", ("frown", "哭臉", "難過")),
    # 裝飾・分隔
    ("❦", "裝飾", ("ornament", "花飾")), ("❧", "裝飾", ("ornament", "花飾")),
    ("☙", "裝飾", ("ornament", "花飾")), ("❀", "裝飾", ("flower", "花")),
    ("✿", "裝飾", ("flower", "花")), ("❁", "裝飾", ("flower", "花")),
    ("❃", "裝飾", ("flower", "花")), ("❆", "裝飾", ("snowflake", "雪花")),
    ("❇", "裝飾", ("sparkle", "閃亮")), ("❈", "裝飾", ("sparkle", "閃亮")),
]


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
