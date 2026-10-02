"""Real-screen check of the panel window (smartime.ui.overlay).

Types into a real text box with the IME active (same harness and safety as
tsf_typing_test: waits until the computer is idle, stops at any real key or
click, restores the previous input method and the user's memory), then
checks that our panel window is visible and docked next to PIME's hint box,
and saves a screenshot of each case:

    python -m smartime.devtools.panel_check out_dir [--richedit]

The backend must run the current code (scripts\\dev-reload.ps1).
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from . import tsf_typing_test as t

CASES = [
    ("correcting", "ji3ee/4dj94k27{ESC}h"),
    ("keys-view", "ji3ee/4dj94k27{ESC}vv{HOME}lll"),
    ("long", "b06c.4283tj x96k27y4b/6b06j6z83fm4u/ jp6k27jp4{ESC}hhh"),
    ("candidates", "ji35p {DOWN}"),
    ("candidates-filter", "mvp {DOWN}{TAB}"),
    ("palette", "ji3{RCTRL}{TAB}{TAB}"),
]

user32 = t.user32
gdi32 = ctypes.WinDLL("gdi32")
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC,
                         ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                            ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]


def rect_of(hwnd) -> tuple[int, int, int, int] | None:
    if not hwnd or not user32.IsWindowVisible(hwnd):
        return None
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def visible_of_class(cls: str) -> list[tuple[int, int, int, int]]:
    out, hwnd = [], None
    for _ in range(64):
        hwnd = user32.FindWindowExW(None, hwnd, cls, None)
        if not hwnd:
            break
        r = rect_of(hwnd)
        if r and r[2] - r[0] > 2:
            out.append(r)
    return out


def screenshot(rect, path: Path) -> None:
    from PIL import Image

    from ..ui import win32 as w32

    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    screen = w32.user32.GetDC(None)
    surf = None
    try:
        from ..ui.canvas import Surface

        surf = Surface(w, h, screen)
        w32.gdi32.BitBlt(surf.hdc, 0, 0, w, h, screen, x0, y0, 0x00CC0020 | 0x40000000)  # SRCCOPY | CAPTUREBLT
        Image.frombytes("RGB", (w, h), surf.rgb_bytes()).save(path)
    finally:
        if surf is not None:
            surf.close()
        w32.user32.ReleaseDC(None, screen)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "panel-check")
    out.mkdir(parents=True, exist_ok=True)
    richedit = "--richedit" in sys.argv
    try:  # physical pixels everywhere (screenshots, window rectangles)
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        pass
    print("waiting until keyboard/mouse have been idle for 5 s ...")
    if not t.wait_until_idle():
        print("ABORT: the computer is in use; try again later (no keys were sent)")
        return 2
    memory = t.MemoryGuard()
    t.ole32.CoInitializeEx(None, 0x2)
    mgr = t.ProfileMgr()
    previous = mgr.active()
    t.GUARD = t.UserGuard()
    win = t.TestWindow(richedit)
    failures = 0
    try:
        if not win.focus():
            print("ABORT: could not bring the test window to the foreground; no keys were sent")
            return 2
        hr = mgr.activate(t.TF_PROFILETYPE_INPUTPROCESSOR, 0x0404, t.guid(t.PIME_CLSID), t.guid(t.PROFILE_GUID),
                          None, t.TF_IPPMF_FORPROCESS | t.TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        if hr != 0:
            print(f"FAIL: ActivateProfile returned {hr & 0xFFFFFFFF:#x}")
            return 1
        t.pump(0.8)
        for name, script in CASES:
            win.set_caption(f"  順打輸入法面板檢查：{name}（碰鍵盤或滑鼠會立即停止）\r\n  按鍵：{script}")
            win.clear()
            t.pump(0.1)
            t.type_script(win.tap, script)
            t.pump(0.8)  # the panel follows PIME's window on a 40 ms timer
            panel = rect_of(user32.FindWindowW("ShundaImePanel", None))
            anchors = visible_of_class("LibImeWindow")
            edit = rect_of(win.hwnd)
            problems = []
            if panel is None:
                problems.append("panel window not visible")
            if not anchors:
                problems.append("no PIME hint window")
            if panel and anchors:
                a = max(anchors, key=lambda r: r[3])
                docked_below = 0 <= panel[1] - a[3] <= 12
                docked_above = panel[3] <= a[1]
                if not (docked_below or docked_above) or abs(panel[0] - a[0]) > 400:
                    problems.append(f"panel {panel} not next to the hint box {a}")
            shot = [r for r in [panel, edit, *anchors] if r]
            if shot:
                box = (min(r[0] for r in shot) - 8, min(r[1] for r in shot) - 8,
                       max(r[2] for r in shot) + 8, max(r[3] for r in shot) + 8)
                screenshot(box, out / f"panel-{name}.png")
            failures += bool(problems)
            print(f"{'FAIL' if problems else 'PASS'}  {name:12} panel={panel} anchors={anchors}"
                  + ("  " + "; ".join(problems) if problems else ""))
            t.type_script(win.tap, "{ESC}{ENTER}")  # close / leave whatever is open, commit
            t.pump(0.3)
        return 1 if failures else 0
    except t.Aborted as e:
        print("ABORT:", e)
        return 2
    finally:
        mgr.activate(previous.dwProfileType, previous.langid, previous.clsid, previous.guidProfile,
                     previous.hkl, t.TF_IPPMF_FORPROCESS | t.TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        win.destroy()
        t.GUARD.close()
        memory.restore()
        t.pump(0.1)


if __name__ == "__main__":
    sys.exit(main())
