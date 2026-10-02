"""Colours and fonts of the on-screen panels.

Colour carries meaning, and only a few meanings, so the panels stay calm:

    accent   blue    where you are: the cursor, the selected candidate
    fix      amber   the IME changed something for you (keys typed out of
                     order were read in order) — and the correction-mode frame
    drop     red     keys that were skipped as strays (struck through)
    memory   green   from your own dictionary or learned from your choices
    predict  purple  suggestions for what comes next

Everything else is neutral text on the panel background; secondary text
(row labels, help lines) is muted. Tokens follow the settings page
(settings/ui/style.css) so the IME looks like one product.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    dark: bool
    bg: int
    surface: int  # headers, the row-label gutter
    border: int
    fg: int
    muted: int
    faint: int
    accent: int
    accent_soft: int
    on_accent: int
    fix: int
    fix_soft: int
    drop: int
    drop_soft: int
    memory: int
    memory_soft: int
    predict: int
    predict_soft: int
    font_ui: str = "Microsoft JhengHei UI"
    font_mono: str = "Consolas"


LIGHT = Theme(
    dark=False, bg=0xFFFFFF, surface=0xF4F6FA, border=0xD3D9E4, fg=0x1B2230, muted=0x5C6577, faint=0x8A93A5,
    accent=0x2563EB, accent_soft=0xDBE6FD, on_accent=0xFFFFFF,
    fix=0xB45309, fix_soft=0xFDF0D5, drop=0xB42318, drop_soft=0xFBE2DF,
    memory=0x15803D, memory_soft=0xDCF2E3, predict=0x7C3AED, predict_soft=0xEDE5FF,
)
DARK = Theme(
    dark=True, bg=0x1E232D, surface=0x262C38, border=0x3A4252, fg=0xE6E9EF, muted=0x9AA3B5, faint=0x6F788B,
    accent=0x6B9BFF, accent_soft=0x1F2D4D, on_accent=0x0B1220,
    fix=0xF2B553, fix_soft=0x3A2A0E, drop=0xFF8A7A, drop_soft=0x3D1A17,
    memory=0x4ADE80, memory_soft=0x143222, predict=0xB79CFF, predict_soft=0x2A1F47,
)


def system_theme() -> Theme:
    """Follow Windows' app mode (Settings > Personalization > Colors)."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return LIGHT if light else DARK
    except OSError:
        return LIGHT


def pick(name: str) -> Theme:
    """"light" | "dark" | "system"."""
    return LIGHT if name == "light" else DARK if name == "dark" else system_theme()
