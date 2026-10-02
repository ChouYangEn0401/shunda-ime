"""Punctuation keys: what each symbol key types, alone, with Shift, with
Ctrl and with Ctrl+Shift — the four layers the settings page lays out.

Default style "keycap" (user feedback #8: "螢幕鍵盤上看得到的都要能打；
鍵位重複就表示還能放更多可能"):

    alone / Shift   exactly what is printed on the keycap (half-width):
                    [ ] ' \\ ` =   < > ? : " { } ( ) ~ ! @ # …
    Ctrl            Chinese punctuation for the lower symbol: ，。；、…—「」
    Ctrl+Shift      the full-width form of the upper symbol: 《》：？！（）『』＂

so no combination types the same thing as another; the other width of any
symbol is one ↓ away in the candidate window. "fullwidth" is the older
Microsoft-like style (Shift+, also types ，); "custom" uses the per-key
choice in ``Config.halfwidth_symbols``. Ctrl / Ctrl+Shift cells can be
changed one by one (``Config.punct_overrides``: "C+," / "CS+/" -> text,
"" = leave the combination to the app).

Ctrl combinations are only taken in the Chinese-side modes; Ctrl+\\ and
Ctrl+Shift+` stay free on purpose (VS Code: split editor, new terminal).
"""

from __future__ import annotations

from .decoder import FULLWIDTH_PUNCT
from .keys import VK_OEM_1, VK_OEM_2, VK_OEM_4, VK_OEM_6, VK_OEM_7, VK_OEM_COMMA, VK_OEM_MINUS, VK_OEM_PERIOD

VK_OEM_PLUS = 0xBB  # =
VK_OEM_3 = 0xC0  # `
VK_OEM_5 = 0xDC  # \\

# Physical keys with a symbol on them: (virtual key, lower, upper), in keyboard order.
KEYCAPS = [
    (VK_OEM_3, "`", "~"),
    *[(0x30 + d, str(d), u) for d, u in zip((1, 2, 3, 4, 5, 6, 7, 8, 9, 0), "!@#$%^&*()")],
    (VK_OEM_MINUS, "-", "_"), (VK_OEM_PLUS, "=", "+"),
    (VK_OEM_4, "[", "{"), (VK_OEM_6, "]", "}"), (VK_OEM_5, "\\", "|"),
    (VK_OEM_1, ";", ":"), (VK_OEM_7, "'", '"'),
    (VK_OEM_COMMA, ",", "<"), (VK_OEM_PERIOD, ".", ">"), (VK_OEM_2, "/", "?"),
]
KEYCAP_OF_VK = {vk: lower for vk, lower, _ in KEYCAPS}

# Ctrl(+Shift)+key -> full-width punctuation, following 微軟新注音 (華碩 uses
# the same convention). Key: (lower keycap, shift held).
CTRL_PUNCT = {
    (",", False): "，", (".", False): "。", (";", False): "；", ("'", False): "、", ("/", False): "…",
    ("-", False): "—", ("[", False): "「", ("]", False): "」",
    (",", True): "《", (".", True): "》", (";", True): "：", ("'", True): "＂", ("/", True): "？",
    ("1", True): "！", ("[", True): "『", ("]", True): "』", ("9", True): "（", ("0", True): "）",
}

STYLES = ("keycap", "fullwidth", "custom")


def halfwidth_set(cfg) -> frozenset[str]:
    """Symbols that type their half-width (keycap) form first."""
    style = getattr(cfg, "punct_style", "custom")
    if style == "keycap":
        return frozenset(FULLWIDTH_PUNCT)
    if style == "fullwidth":
        return frozenset('"')
    return frozenset(cfg.halfwidth_symbols)


def combo_name(lower: str, shift: bool) -> str:
    return ("CS+" if shift else "C+") + lower


def ctrl_output(cfg, vk: int, shift: bool) -> str | None:
    """What Ctrl(+Shift)+key types (None: the combination goes to the app)."""
    lower = KEYCAP_OF_VK.get(vk)
    if lower is None:
        return None
    override = cfg.punct_overrides.get(combo_name(lower, shift))
    if override is not None:
        return override or None
    return CTRL_PUNCT.get((lower, shift))


def table(cfg, layout) -> list[dict]:
    """Every symbol key and what it types in each layer (settings page)."""
    half = halfwidth_set(cfg)

    def plain_out(ch: str) -> tuple[str, str]:
        if layout.symbol(ch) or layout.tone(ch) is not None:
            return (layout.symbol(ch) or layout.tone(ch) or "一聲"), "zhuyin"
        if ch in FULLWIDTH_PUNCT:
            return (ch if ch in half else FULLWIDTH_PUNCT[ch]), "symbol"
        return ch, "symbol"

    rows = []
    for vk, lower, upper in KEYCAPS:
        alone, alone_kind = plain_out(lower)
        shift = upper if upper not in FULLWIDTH_PUNCT or upper in half else FULLWIDTH_PUNCT[upper]
        rows.append({
            "key": lower, "upper": upper,
            "alone": alone, "aloneKind": alone_kind,
            "aloneAlt": FULLWIDTH_PUNCT.get(lower, ""), "shift": shift, "shiftAlt": FULLWIDTH_PUNCT.get(upper, ""),
            "ctrl": ctrl_output(cfg, vk, False) or "", "ctrlDefault": CTRL_PUNCT.get((lower, False), ""),
            "ctrlShift": ctrl_output(cfg, vk, True) or "", "ctrlShiftDefault": CTRL_PUNCT.get((lower, True), ""),
        })
    return rows
