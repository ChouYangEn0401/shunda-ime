"""Win32 pieces of the voice service (ctypes only): the push-to-talk
keyboard hook, a small "recording" indicator, and typing text at the cursor.
Everything here runs on the service's main thread, which pumps messages."""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes

from ..engine.keys import INJECTED_TAG

log = logging.getLogger(__name__)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_APP = 0x8000
WM_SETFONT = 0x0030
WM_TIMER = 0x0113
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
VK_RCONTROL = 0xA3
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
WS_POPUP, WS_VISIBLE, WS_BORDER = 0x80000000, 0x10000000, 0x00800000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
SS_CENTER, SS_CENTERIMAGE = 0x1, 0x200
SW_HIDE = 0
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
MONITOR_DEFAULTTOPRIMARY = 1
DWMWA_CLOAKED = 14
# Broadcasts: they reach top-level windows only, never message-only ones.
WM_POWERBROADCAST, WM_DEVICECHANGE, WM_WTSSESSION_CHANGE = 0x0218, 0x0219, 0x02B1
PBT_APMSUSPEND, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 0x4, 0x7, 0x12
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 0x7, 0x8
DBT_DEVNODES_CHANGED = 0x0007


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]


def single_instance(name: str) -> bool:
    """True if this is the only process holding the named mutex."""
    kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def type_text(text: str) -> None:
    """Type Unicode text into the focused window (KEYEVENTF_UNICODE, one
    UTF-16 code unit per event; surrogate pairs are two events)."""
    data = text.encode("utf-16-le")
    units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
    events = []
    for u in units:
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.u.ki = KEYBDINPUT(wVk=0, wScan=u, dwFlags=flags, dwExtraInfo=INJECTED_TAG)
            events.append(inp)
    for i in range(0, len(events), 64):  # small batches keep apps responsive
        chunk = events[i:i + 64]
        arr = (INPUT * len(chunk))(*chunk)
        user32.SendInput(len(chunk), arr, ctypes.sizeof(INPUT))


def set_clipboard(hwnd, text: str) -> bool:
    """Put text on the clipboard. Another program may hold it open for a
    moment, so try for a little while."""
    data = text.encode("utf-16-le") + b"\0\0"
    for _ in range(25):
        if user32.OpenClipboard(hwnd):
            break
        time.sleep(0.02)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ctypes.memmove(kernel32.GlobalLock(handle), data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True  # the clipboard owns the memory now
    finally:
        user32.CloseClipboard()


class MessageWindow:
    """A hidden window whose procedure dispatches messages to Python
    callbacks; worker threads post to it to run code on the main thread.

    Top-level (never shown), not message-only: sleep/resume and device
    changes are broadcast, and broadcasts skip message-only windows."""

    PASS_ON = {WM_POWERBROADCAST, WM_DEVICECHANGE}  # Windows reads the answer: give the default one

    def __init__(self, handlers: dict):
        self.handlers = handlers
        self._proc = WNDPROC(self._wndproc)  # keep a reference
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="SmartIMEVoiceMsg")
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW, "SmartIMEVoiceMsg", "", WS_POPUP,
                                           0, 0, 0, 0, None, None, hinst, None)
        if not wtsapi32.WTSRegisterSessionNotification(self.hwnd, 0):  # NOTIFY_FOR_THIS_SESSION
            log.warning("no lock/unlock notifications (error %d)", ctypes.get_last_error())

    def _wndproc(self, hwnd, msg, wparam, lparam):
        handler = self.handlers.get(msg)
        if handler is not None:
            try:
                handler(wparam, lparam)
            except Exception:  # noqa: BLE001 - never let an exception cross into Windows
                log.exception("message handler failed")
            if msg not in self.PASS_ON:
                return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def post(self, msg: int, wparam: int = 0, lparam: int = 0) -> None:
        user32.PostMessageW(self.hwnd, msg, wparam, lparam)


def bottom_center(area: tuple[int, int, int, int], w: int, h: int, margin: int = 40) -> tuple[int, int]:
    """Where the indicator goes in a monitor's work area (left, top, right, bottom)."""
    left, _, right, bottom = area
    return left + (right - left - w) // 2, bottom - h - margin


def work_area() -> tuple[int, int, int, int]:
    """Work area of the monitor the user is looking at: the one with the
    foreground window (the primary monitor when there is none)."""
    mon = user32.MonitorFromWindow(user32.GetForegroundWindow(), MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def key_down(vk: int) -> bool:
    """Is the key physically held right now (no hook needed)? False while
    another desktop (lock screen, UAC) has the keyboard."""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class Indicator:
    """A small floating label at the bottom of the screen the user is
    working on; it never takes the focus (the text must go to the window the
    user was typing in).

    Reported: after a while — a full-screen film on the other monitor, sleep —
    the label stopped appearing although recording worked. It used to be
    one window, placed once on the primary monitor at start-up and shown
    with ShowWindow, which keeps whatever z-order and virtual desktop the
    window had. Now every appearance gets a fresh window on the current
    monitor and virtual desktop, put back on top of the topmost windows."""

    W, H = 460, 46

    def __init__(self) -> None:
        self.hwnd = None
        self.font = gdi32.CreateFontW(-20, 0, 0, 0, 500, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft JhengHei UI")
        self._warned = False

    def _create(self):
        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "STATIC", "",
            WS_POPUP | WS_BORDER | SS_CENTER | SS_CENTERIMAGE,
            0, 0, self.W, self.H, None, None, kernel32.GetModuleHandleW(None), None)
        if hwnd:
            user32.SendMessageW(hwnd, WM_SETFONT, self.font, 0)
        return hwnd

    def show(self, text: str) -> None:
        if not (self.hwnd and user32.IsWindow(self.hwnd) and user32.IsWindowVisible(self.hwnd)):
            if self.hwnd and user32.IsWindow(self.hwnd):
                user32.DestroyWindow(self.hwnd)
            self.hwnd = self._create()
            if not self.hwnd:
                self._warn(f"cannot create the indicator window (error {ctypes.get_last_error()})")
                return
        user32.SetWindowTextW(self.hwnd, text)
        x, y = bottom_center(work_area(), self.W, self.H)
        if not user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, self.W, self.H, SWP_NOACTIVATE | SWP_SHOWWINDOW):
            self._warn(f"SetWindowPos failed (error {ctypes.get_last_error()})")
        cloaked = wintypes.DWORD()
        dwmapi.DwmGetWindowAttribute(self.hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value or not user32.IsWindowVisible(self.hwnd):
            self._warn(f"indicator not visible at ({x}, {y}): cloaked={cloaked.value}")

    def _warn(self, message: str) -> None:
        """Once per run: voice.log says why the label was missing."""
        if not self._warned:
            self._warned = True
            log.warning(message)

    def hide(self) -> None:
        if self.hwnd:
            user32.ShowWindow(self.hwnd, SW_HIDE)


class PushToTalkHook:
    """Low-level keyboard hook for "hold right Ctrl to talk". It lives on
    its own thread with its own message loop, so the main thread opening the
    microphone or typing a long result never delays anyone's keyboard (a
    slow hook lags every key on the PC, and Windows drops hooks that time
    out). It only tracks state and posts to the main thread's message
    window. Keys are never swallowed."""

    PRESS, RELEASE, CANCEL = WM_APP + 1, WM_APP + 2, WM_APP + 3
    REINSTALL = WM_APP + 20  # a thread message to the hook's own thread

    def __init__(self, target: MessageWindow, accept_injected: bool = False, start: bool = True):
        self.target = target
        self.accept_injected = accept_injected  # devtools.voice_test presses right Ctrl with SendInput
        self.down = False
        self.combo = False
        # Last right-Ctrl key-down seen, keyboard auto-repeats included: while
        # the key is really held they keep coming, so a stale time means the
        # release happened somewhere the hook could not see.
        self.last_down = 0.0
        self.handle = None
        self._proc = HOOKPROC(self._hook)
        self._thread_id = 0
        if not start:  # tests drive on_key() directly
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), name="ptt-hook", daemon=True)
        self._thread.start()
        ready.wait(5)

    def _install(self):
        return user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)

    def _run(self, ready: threading.Event) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self.handle = self._install()
        ready.set()
        # hook callbacks are delivered while this thread waits for messages
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.hwnd is None and msg.message == self.REINSTALL:
                self._reinstall_now()
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self.handle:
            user32.UnhookWindowsHookEx(self.handle)
            self.handle = None

    def _reinstall_now(self) -> None:
        """Windows removes a low-level hook that once answered too slowly,
        without telling anyone (busy right after resume, or under a game's
        load). A new hook first, then the old one goes: no key is missed."""
        new = self._install()
        if not new:
            log.warning("cannot reinstall the keyboard hook (error %d)", ctypes.get_last_error())
            return
        old, self.handle = self.handle, new
        if old:
            user32.UnhookWindowsHookEx(old)  # fails harmlessly if Windows removed it already

    def reinstall(self) -> None:
        """From any thread."""
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, self.REINSTALL, 0, 0)

    def reset(self) -> None:
        """Forget a press whose release went elsewhere (sleep, lock screen,
        UAC prompt), so the next press starts afresh."""
        self.down = self.combo = False

    def _hook(self, code, wparam, lparam):
        if code == 0:
            k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            ours = self.accept_injected and k.dwExtraInfo == INJECTED_TAG
            if ours or not k.flags & LLKHF_INJECTED:
                self.on_key(k.vkCode, wparam in (WM_KEYDOWN, WM_SYSKEYDOWN))
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def on_key(self, vk: int, is_down: bool) -> None:
        if vk == VK_RCONTROL:
            if is_down:
                self.last_down = time.monotonic()
                if not self.down:
                    self.down, self.combo = True, False
                    self.target.post(self.PRESS)
            elif self.down:
                self.down = False
                self.target.post(self.CANCEL if self.combo else self.RELEASE)
        elif is_down and self.down and not self.combo:
            self.combo = True  # right Ctrl + another key = a shortcut
            self.target.post(self.CANCEL)

    def close(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(2)


def run_message_loop() -> None:
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def quit_message_loop() -> None:
    user32.PostQuitMessage(0)
