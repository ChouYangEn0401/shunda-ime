"""A small drawing API over a GDI device context.

Coordinates are logical pixels (96-DPI); the canvas scales them. The same
code draws into the panel window and into an offscreen bitmap (used by the
preview tool and for double buffering), so what the preview shows is what
the user sees.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import win32 as w
from .win32 import gdi32, rgb


class Fonts:
    """HFONTs by (face, size, weight, underline, strike), created once per scale."""

    def __init__(self, scale: float):
        self.scale = scale
        self._cache: dict[tuple, int] = {}

    def get(self, face: str, size: float, weight: int = 400, underline: bool = False, strike: bool = False) -> int:
        key = (face, size, weight, underline, strike)
        f = self._cache.get(key)
        if f is None:
            f = gdi32.CreateFontW(-max(1, round(size * self.scale)), 0, 0, 0, weight, 0, int(underline), int(strike),
                                  w.DEFAULT_CHARSET, 0, 0, w.CLEARTYPE_QUALITY, 0, face)
            self._cache[key] = f
        return f

    def close(self) -> None:
        for f in self._cache.values():
            gdi32.DeleteObject(f)
        self._cache.clear()


class Canvas:
    def __init__(self, hdc: int, scale: float, fonts: Fonts):
        self.hdc = hdc
        self.scale = scale
        self.fonts = fonts
        gdi32.SetBkMode(hdc, w.TRANSPARENT)
        self._brushes: dict[int, int] = {}
        self._pens: dict[tuple[int, int], int] = {}
        self._ascents: dict[int, float] = {}

    # ------------------------------------------------------------ helpers
    def px(self, v: float) -> int:
        return round(v * self.scale)

    def _brush(self, color: int) -> int:
        b = self._brushes.get(color)
        if b is None:
            b = self._brushes[color] = gdi32.CreateSolidBrush(rgb(color))
        return b

    def _pen(self, color: int, width: float) -> int:
        key = (color, max(1, self.px(width)))
        p = self._pens.get(key)
        if p is None:
            p = self._pens[key] = gdi32.CreatePen(w.PS_SOLID, key[1], rgb(color))
        return p

    def close(self) -> None:
        for h in list(self._brushes.values()) + list(self._pens.values()):
            gdi32.DeleteObject(h)
        self._brushes.clear()
        self._pens.clear()

    # ------------------------------------------------------------ text
    def measure(self, text: str, font: int) -> tuple[float, float]:
        if not text:
            text = " "
            empty = True
        else:
            empty = False
        old = gdi32.SelectObject(self.hdc, font)
        size = w.SIZE()
        gdi32.GetTextExtentPoint32W(self.hdc, text, len(text), ctypes.byref(size))
        gdi32.SelectObject(self.hdc, old)
        return (0.0 if empty else size.cx / self.scale), size.cy / self.scale

    def ascent(self, font: int) -> float:
        """Distance from the top of the text cell to the baseline."""
        a = self._ascents.get(font)
        if a is None:
            old = gdi32.SelectObject(self.hdc, font)
            tm = w.TEXTMETRICW()
            gdi32.GetTextMetricsW(self.hdc, ctypes.byref(tm))
            gdi32.SelectObject(self.hdc, old)
            a = self._ascents[font] = tm.tmAscent / self.scale
        return a

    def text(self, x: float, y: float, text: str, font: int, color: int) -> None:
        if not text:
            return
        old = gdi32.SelectObject(self.hdc, font)
        gdi32.SetTextColor(self.hdc, rgb(color))
        gdi32.ExtTextOutW(self.hdc, self.px(x), self.px(y), 0, None, text, len(text), None)
        gdi32.SelectObject(self.hdc, old)

    def text_center(self, x: float, y: float, width: float, text: str, font: int, color: int) -> None:
        tw, _ = self.measure(text, font)
        self.text(x + (width - tw) / 2, y, text, font, color)

    # ------------------------------------------------------------ shapes
    def fill(self, x: float, y: float, width: float, height: float, color: int, radius: float = 0) -> None:
        if radius <= 0:
            r = wintypes.RECT(self.px(x), self.px(y), self.px(x + width), self.px(y + height))
            w.user32.FillRect(self.hdc, ctypes.byref(r), self._brush(color))
            return
        old_pen = gdi32.SelectObject(self.hdc, gdi32.GetStockObject(w.NULL_PEN))
        old_brush = gdi32.SelectObject(self.hdc, self._brush(color))
        d = self.px(radius * 2)
        # NULL_PEN: RoundRect paints one pixel short on the right/bottom
        gdi32.RoundRect(self.hdc, self.px(x), self.px(y), self.px(x + width) + 1, self.px(y + height) + 1, d, d)
        gdi32.SelectObject(self.hdc, old_brush)
        gdi32.SelectObject(self.hdc, old_pen)

    def stroke(self, x: float, y: float, width: float, height: float, color: int, radius: float = 0,
               line: float = 1) -> None:
        old_pen = gdi32.SelectObject(self.hdc, self._pen(color, line))
        old_brush = gdi32.SelectObject(self.hdc, gdi32.GetStockObject(w.NULL_BRUSH))
        d = self.px(radius * 2)
        gdi32.RoundRect(self.hdc, self.px(x), self.px(y), self.px(x + width), self.px(y + height), d, d)
        gdi32.SelectObject(self.hdc, old_brush)
        gdi32.SelectObject(self.hdc, old_pen)

    def hline(self, x1: float, x2: float, y: float, color: int, line: float = 1) -> None:
        self.fill(x1, y, x2 - x1, line, color)

    def vline(self, x: float, y1: float, y2: float, color: int, line: float = 1) -> None:
        self.fill(x, y1, line, y2 - y1, color)


class Surface:
    """An offscreen 32-bit bitmap to draw into (double buffering, previews)."""

    def __init__(self, width_px: int, height_px: int, ref_dc: int | None = None):
        self.width, self.height = max(1, width_px), max(1, height_px)
        self.hdc = gdi32.CreateCompatibleDC(ref_dc)
        bmi = w.BITMAPINFOHEADER(biSize=ctypes.sizeof(w.BITMAPINFOHEADER), biWidth=self.width,
                                 biHeight=-self.height, biPlanes=1, biBitCount=32, biCompression=w.BI_RGB)
        self.bits = ctypes.c_void_p()
        self.bitmap = gdi32.CreateDIBSection(self.hdc, ctypes.byref(bmi), w.DIB_RGB_COLORS, ctypes.byref(self.bits),
                                             None, 0)
        self._old = gdi32.SelectObject(self.hdc, self.bitmap)

    def blit_to(self, hdc: int) -> None:
        gdi32.BitBlt(hdc, 0, 0, self.width, self.height, self.hdc, 0, 0, w.SRCCOPY)

    def rgb_bytes(self) -> bytes:
        """Pixels as RGB rows (top to bottom), for saving a preview."""
        raw = ctypes.string_at(self.bits, self.width * self.height * 4)
        out = bytearray(self.width * self.height * 3)
        out[0::3] = raw[2::4]
        out[1::3] = raw[1::4]
        out[2::3] = raw[0::4]
        return bytes(out)

    def close(self) -> None:
        gdi32.SelectObject(self.hdc, self._old)
        gdi32.DeleteObject(self.bitmap)
        gdi32.DeleteDC(self.hdc)
