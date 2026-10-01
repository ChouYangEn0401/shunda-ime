"""Win32 pieces of the voice service (ctypes only): the push-to-talk
keyboard hook, a small "recording" indicator, and typing text at the cursor.
Everything here runs on the service's main thread, which pumps messages."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")

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
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_MESSAGE = wintypes.HWND(-3)


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
            inp.u.ki = KEYBDINPUT(wVk=0, wScan=u, dwFlags=flags)
            events.append(inp)
    for i in range(0, len(events), 64):  # small batches keep apps responsive
        chunk = events[i:i + 64]
        arr = (INPUT * len(chunk))(*chunk)
        user32.SendInput(len(chunk), arr, ctypes.sizeof(INPUT))


class MessageWindow:
    """A hidden window whose procedure dispatches WM_APP+n messages to
    Python callbacks; worker threads post to it to run code on the main
    thread."""

    def __init__(self, handlers: dict):
        self.handlers = handlers
        self._proc = WNDPROC(self._wndproc)  # keep a reference
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="SmartIMEVoiceMsg")
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "SmartIMEVoiceMsg", "", 0, 0, 0, 0, 0, HWND_MESSAGE, None, hinst, None)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        handler = self.handlers.get(msg)
        if handler is not None:
            try:
                handler(wparam, lparam)
            except Exception:  # noqa: BLE001 - never let an exception cross into Windows
                import logging

                logging.getLogger(__name__).exception("message handler failed")
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def post(self, msg: int, wparam: int = 0, lparam: int = 0) -> None:
        user32.PostMessageW(self.hwnd, msg, wparam, lparam)


class Indicator:
    """A small floating label near the bottom of the screen that never takes
    the focus (the text must go to the window the user was typing in)."""

    def __init__(self) -> None:
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        w, h = 460, 46
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "STATIC", "",
            WS_POPUP | WS_BORDER | SS_CENTER | SS_CENTERIMAGE,
            (sw - w) // 2, sh - h - 90, w, h, None, None, kernel32.GetModuleHandleW(None), None)
        font = gdi32.CreateFontW(-20, 0, 0, 0, 500, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft JhengHei UI")
        user32.SendMessageW(self.hwnd, WM_SETFONT, font, 1)

    def show(self, text: str) -> None:
        user32.SetWindowTextW(self.hwnd, text)
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def hide(self) -> None:
        user32.ShowWindow(self.hwnd, SW_HIDE)


class PushToTalkHook:
    """Low-level keyboard hook for "hold right Ctrl to talk". It lives on
    its own thread with its own message loop, so the main thread opening the
    microphone or typing a long result never delays anyone's keyboard (a
    slow hook lags every key on the PC, and Windows drops hooks that time
    out). It only tracks state and posts to the main thread's message
    window. Keys are never swallowed."""

    PRESS, RELEASE, CANCEL = WM_APP + 1, WM_APP + 2, WM_APP + 3

    def __init__(self, target: MessageWindow, accept_injected: bool = False):
        self.target = target
        self.accept_injected = accept_injected  # devtools.voice_test presses the key with SendInput
        self.down = False
        self.combo = False
        self.handle = None
        self._proc = HOOKPROC(self._hook)
        self._thread_id = 0
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), name="ptt-hook", daemon=True)
        self._thread.start()
        ready.wait(5)

    def _run(self, ready: threading.Event) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self.handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        ready.set()
        run_message_loop()  # hook callbacks are delivered while this thread waits for messages
        if self.handle:
            user32.UnhookWindowsHookEx(self.handle)
            self.handle = None

    def _hook(self, code, wparam, lparam):
        if code == 0:
            k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if self.accept_injected or not k.flags & LLKHF_INJECTED:
                is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                if k.vkCode == VK_RCONTROL:
                    if is_down and not self.down:
                        self.down, self.combo = True, False
                        self.target.post(self.PRESS)
                    elif not is_down and self.down:
                        self.down = False
                        self.target.post(self.CANCEL if self.combo else self.RELEASE)
                elif is_down and self.down and not self.combo:
                    self.combo = True  # right Ctrl + another key = a shortcut
                    self.target.post(self.CANCEL)
        return user32.CallNextHookEx(None, code, wparam, lparam)

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
