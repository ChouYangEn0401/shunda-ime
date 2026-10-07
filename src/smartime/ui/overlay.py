"""The panel window: our own drawing next to the composition.

PIME's candidate and message windows can only show plain text, so the
panels (decode view, correction mode frame, grouped candidates …) are drawn
by the backend itself in a window that never takes the focus.

Where is the composition? Only the app's process knows (TSF GetTextExt),
but PIME already uses it to place its yellow message window
(class "LibImeWindow") right under the caret. So the panel docks under
that window; without one it falls back to the system caret
(GetGUIThreadInfo), and hides if neither is found. A timer keeps following
the anchor while the panel is visible (PIME moves its window after our
reply has been applied).

Threading: the backend's main thread handles PIME requests; this module
runs its own UI thread with a message loop. ``show``/``hide`` only store
the request and post a message, so they never block typing.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes

from . import win32 as w
from .canvas import Canvas, Fonts, Surface
from .panels import paint_candidates, paint_decode, paint_hint, paint_smart
from .theme import Theme
from .win32 import user32

log = logging.getLogger(__name__)

CLASS_NAME = "ShundaImePanel"
ANCHOR_CLASS = "LibImeWindow"  # PIME's candidate / message windows
WM_UPDATE = w.WM_APP + 1
WM_STOP = w.WM_APP + 2
TIMER_FOLLOW = 1
FOLLOW_MS = 40
LOST_ANCHOR_SECONDS = 0.6  # hide when the composition's window has been gone this long
GAP = 4

PAINTERS = {"decode": paint_decode, "candidates": paint_candidates, "smart": paint_smart,
            "hint": paint_hint}


def _rect(r: wintypes.RECT) -> tuple[int, int, int, int]:
    return r.left, r.top, r.right, r.bottom


def find_own(class_name: str) -> tuple[int, int, int, int] | None:
    """Our other panel window, if it is showing (the second panel docks under it)."""
    hwnd = user32.FindWindowExW(None, None, class_name, None)
    if not hwnd or not user32.IsWindowVisible(hwnd):
        return None
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return _rect(r)


# A PIME window no wider/taller than this is its hint box, not its candidate
# list (one space of DEFAULT_GUI_FONT plus a 5 px margin each side). Only the
# hint box may be made invisible: the candidate list is what the user clicks.
STUB_MAX_W, STUB_MAX_H = 64, 56


def hide_stub(hwnd: int) -> None:
    """Make PIME's hint box invisible without closing it.

    We need the window: PIME puts it right under the caret and moves it on
    every composition update, which is the only way this process can know
    where the text is. We do not want to *see* it — it is a Windows 95
    tooltip (pale yellow, 3-D border) that PIME destroys and recreates on
    every change. Layering it at alpha 0 leaves the anchor exactly where it
    is and draws nothing.
    """
    try:
        ex = user32.GetWindowLongW(hwnd, w.GWL_EXSTYLE)
        if not ex & w.WS_EX_LAYERED:
            user32.SetWindowLongW(hwnd, w.GWL_EXSTYLE, ex | w.WS_EX_LAYERED | w.WS_EX_TRANSPARENT)
        user32.SetLayeredWindowAttributes(hwnd, 0, 0, w.LWA_ALPHA)
    except Exception:  # noqa: BLE001 - a visible stub is better than no typing
        log.debug("cannot hide PIME's hint box", exc_info=True)


def find_anchor() -> tuple[tuple[int, int, int, int], int] | None:
    """(screen rectangle, window) of PIME's visible window in the foreground
    app, else in any app (UWP apps run inside ApplicationFrameHost)."""
    fg = user32.GetForegroundWindow()
    fg_pid = wintypes.DWORD()
    if fg:
        user32.GetWindowThreadProcessId(fg, ctypes.byref(fg_pid))
    mine, anywhere = [], []
    hwnd = None
    for _ in range(64):
        hwnd = user32.FindWindowExW(None, hwnd, ANCHOR_CLASS, None)
        if not hwnd:
            break
        if not user32.IsWindowVisible(hwnd):
            continue
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left < 2:
            continue
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        (mine if pid.value == fg_pid.value else anywhere).append((_rect(r), hwnd))
    found = mine or anywhere
    if not found:
        return None
    # the message window sits under the caret; when the candidate window is
    # open too, dock under whichever is lower
    return max(found, key=lambda x: x[0][3])


def caret_rect() -> tuple[int, int, int, int] | None:
    """The system caret of the foreground thread, in screen coordinates."""
    fg = user32.GetForegroundWindow()
    if not fg:
        return None
    tid = user32.GetWindowThreadProcessId(fg, None)
    info = w.GUITHREADINFO(cbSize=ctypes.sizeof(w.GUITHREADINFO))
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)) or not info.hwndCaret:
        return None
    tl = wintypes.POINT(info.rcCaret.left, info.rcCaret.top)
    br = wintypes.POINT(info.rcCaret.right, info.rcCaret.bottom)
    user32.ClientToScreen(info.hwndCaret, ctypes.byref(tl))
    user32.ClientToScreen(info.hwndCaret, ctypes.byref(br))
    return tl.x, tl.y, br.x, br.y


def work_area(rect: tuple[int, int, int, int]) -> tuple[tuple[int, int, int, int], int]:
    """(work area of the monitor showing ``rect``, its DPI)."""
    r = wintypes.RECT(*rect)
    mon = user32.MonitorFromRect(ctypes.byref(r), w.MONITOR_DEFAULTTONEAREST)
    mi = w.MONITORINFO(cbSize=ctypes.sizeof(w.MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    dpi = 96
    if w.shcore is not None:
        dx, dy = wintypes.UINT(), wintypes.UINT()
        if w.shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
            dpi = dx.value or 96
    return _rect(mi.rcWork), dpi


class Overlay:
    """One panel window per backend process; the input context that showed
    it last owns it."""

    def __init__(self, class_name: str = CLASS_NAME, dock_under: str | None = None) -> None:
        self.class_name = class_name
        self.dock_under = dock_under  # dock under this other panel window when it shows
        self._lock = threading.Lock()
        self._want: tuple | None = None  # (owner, kind, model, theme, size) or None = hidden
        self._owner = None
        self._hwnd = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._failed = False
        self._thread = threading.Thread(target=self._run, name="panel-ui", daemon=True)
        self._thread.start()
        self._ready.wait(3)

    # ------------------------------------------------------------ main thread API
    @property
    def available(self) -> bool:
        return self._hwnd is not None and not self._failed

    def show(self, owner, kind: str, model, theme: Theme, size: float = 1.0, cover: bool = False) -> None:
        """``cover``: sit exactly where PIME's hint box is (and hide it)
        instead of docking under it — the hint box is then only an anchor."""
        with self._lock:
            self._want = (owner, kind, model, theme, size, cover)
            self._owner = owner
        self._post(WM_UPDATE)

    def hide(self, owner=None) -> None:
        with self._lock:
            if owner is not None and owner != self._owner:
                return  # another input context has shown something since
            if self._want is None:
                return
            self._want = None
        self._post(WM_UPDATE)

    def close(self) -> None:
        self._post(WM_STOP)
        self._thread.join(2)

    def _post(self, msg: int) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, msg, 0, 0)

    # ------------------------------------------------------------ UI thread
    def _run(self) -> None:
        try:
            if hasattr(user32, "SetThreadDpiAwarenessContext"):
                user32.SetThreadDpiAwarenessContext(w.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            self._proc = w.WNDPROC(self._wndproc)  # keep a reference
            hinst = w.kernel32.GetModuleHandleW(None)
            wc = w.WNDCLASSEXW(cbSize=ctypes.sizeof(w.WNDCLASSEXW), style=w.CS_DROPSHADOW, lpfnWndProc=self._proc,
                               hInstance=hinst, lpszClassName=self.class_name)
            user32.RegisterClassExW(ctypes.byref(wc))
            ex = w.WS_EX_TOPMOST | w.WS_EX_TOOLWINDOW | w.WS_EX_NOACTIVATE
            self._hwnd = user32.CreateWindowExW(ex, self.class_name, "順打輸入法面板", w.WS_POPUP, 0, 0, 10, 10,
                                                None, None, hinst, None)
            if w.dwmapi is not None:
                pref = ctypes.c_int(w.DWMWCP_ROUNDSMALL)
                w.dwmapi.DwmSetWindowAttribute(self._hwnd, w.DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), 4)
            self._thread_id = w.kernel32.GetCurrentThreadId()
        except Exception:  # noqa: BLE001 - the panel is optional; typing must go on
            log.exception("cannot create the panel window")
            self._failed = True
            self._ready.set()
            return
        self._ready.set()
        self._shown: tuple | None = None
        self._size = (0, 0)
        self._scale = 0.0
        self._fonts: Fonts | None = None
        self._last_anchor_at = 0.0
        self._pos: tuple[int, int] | None = None
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._fonts:
            self._fonts.close()
        user32.DestroyWindow(self._hwnd)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_UPDATE:
                self._update()
                return 0
            if msg == w.WM_TIMER and wparam == TIMER_FOLLOW:
                self._follow()
                return 0
            if msg == w.WM_PAINT:
                self._paint(hwnd)
                return 0
            if msg == w.WM_ERASEBKGND:
                return 1
            if msg == w.WM_MOUSEACTIVATE:
                return w.MA_NOACTIVATE  # never take the focus from the app
            if msg == WM_STOP:
                user32.PostQuitMessage(0)
                return 0
        except Exception:  # noqa: BLE001 - never let an exception cross into Windows
            log.exception("panel window message %#x failed", msg)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _update(self) -> None:
        with self._lock:
            want = self._want
        if want is None:
            if self._shown is not None:
                user32.ShowWindow(self._hwnd, w.SW_HIDE)
                user32.KillTimer(self._hwnd, TIMER_FOLLOW)
                self._shown = None
                self._pos = None
            return
        first = self._shown is None
        self._shown = want
        self._last_anchor_at = time.monotonic()
        self._place(resize=True)
        if first:
            user32.SetTimer(self._hwnd, TIMER_FOLLOW, FOLLOW_MS, None)

    def _follow(self) -> None:
        if self._shown is None:
            return
        if not self._place(resize=False) and time.monotonic() - self._last_anchor_at > LOST_ANCHOR_SECONDS:
            # the app lost the composition (focus moved, window closed …)
            with self._lock:
                self._want = None
            self._update()

    def _measure(self, scale: float) -> tuple[int, int]:
        _, kind, model, theme, size, _cover = self._shown
        surf = Surface(4, 4)
        try:
            painted = PAINTERS[kind](Canvas(surf.hdc, scale, self._fonts), theme, model, size, draw=False)
        finally:
            surf.close()
        return round(painted.width * scale) + 1, round(painted.height * scale) + 1

    def _place(self, resize: bool) -> bool:
        """Position (and with ``resize`` size + repaint) next to the anchor.
        Returns whether an anchor was found."""
        cover = bool(self._shown and self._shown[5])
        anchor = find_own(self.dock_under) if self.dock_under else None
        if anchor is not None:
            cover = False  # docking under our own other panel
        else:
            found = find_anchor()
            if found is None:
                anchor = None
            else:
                anchor, anchor_hwnd = found
                is_stub = (anchor[2] - anchor[0] <= STUB_MAX_W * (self._scale or 1.0)
                           and anchor[3] - anchor[1] <= STUB_MAX_H * (self._scale or 1.0))
                if cover and is_stub:
                    hide_stub(anchor_hwnd)
                else:
                    cover = False  # PIME's candidate list: never cover or hide it
        below = True
        if anchor is None:
            anchor = caret_rect()
            cover = False
            if anchor is None:
                if resize and self._pos is not None:
                    self._resize_and_paint()
                return False
        self._last_anchor_at = time.monotonic()
        area, dpi = work_area(anchor)
        scale = dpi / 96
        if scale != self._scale or self._fonts is None:
            if self._fonts:
                self._fonts.close()
            self._fonts = Fonts(scale)
            self._scale = scale
            resize = True
        if resize:
            self._size = self._measure(scale)
        width, height = self._size
        # covering: the stub already sits right under the caret line
        x, y = anchor[0], (anchor[1] if cover else anchor[3] + GAP)
        if y + height > area[3]:
            # no room below: above the composition line (the anchor sits one
            # line below the caret, about its own height)
            line = max(16, anchor[3] - anchor[1])
            y = anchor[1] - line - height - GAP
            below = False
        x = max(area[0], min(x, area[2] - width))
        y = max(area[1], y)
        flags = w.SWP_NOACTIVATE | w.SWP_SHOWWINDOW
        if resize or (x, y) != self._pos:
            user32.SetWindowPos(self._hwnd, w.HWND_TOPMOST, x, y, width, height, flags)
            self._pos = (x, y)
        if resize:
            user32.InvalidateRect(self._hwnd, None, False)
        self._below = below
        return True

    def _resize_and_paint(self) -> None:
        self._size = self._measure(self._scale or 1.0)
        x, y = self._pos
        user32.SetWindowPos(self._hwnd, w.HWND_TOPMOST, x, y, *self._size, w.SWP_NOACTIVATE | w.SWP_SHOWWINDOW)
        user32.InvalidateRect(self._hwnd, None, False)

    def _paint(self, hwnd) -> None:
        ps = w.PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            if self._shown is None or self._fonts is None:
                return
            _, kind, model, theme, size, _cover = self._shown
            width, height = self._size
            surf = Surface(width, height, hdc)
            canvas = Canvas(surf.hdc, self._scale, self._fonts)
            try:
                PAINTERS[kind](canvas, theme, model, size)
                surf.blit_to(hdc)
            finally:
                canvas.close()
                surf.close()
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))


_overlay: Overlay | None = None
_overlay_failed = False
_second: Overlay | None = None
_second_failed = False
SECOND_CLASS = "ShundaImePanel2"


def get() -> Overlay | None:
    """The process's panel window, created on first use (None if it cannot be)."""
    global _overlay, _overlay_failed
    if os.environ.get("SMARTIME_NO_PANEL"):
        return None  # tests, simulators
    if _overlay is None and not _overlay_failed:
        try:
            _overlay = Overlay()
            if not _overlay.available:
                _overlay_failed = True
                _overlay = None
        except Exception:  # noqa: BLE001
            log.exception("panel window unavailable")
            _overlay_failed = True
    return _overlay


def get_second() -> Overlay | None:
    """A second panel window (超智慧推薦) that docks under the first one
    when it is showing, else under PIME's hint box."""
    global _second, _second_failed
    if os.environ.get("SMARTIME_NO_PANEL"):
        return None
    if _second is None and not _second_failed:
        try:
            _second = Overlay(SECOND_CLASS, dock_under=CLASS_NAME)
            if not _second.available:
                _second_failed = True
                _second = None
        except Exception:  # noqa: BLE001
            log.exception("second panel window unavailable")
            _second_failed = True
    return _second
