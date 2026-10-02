"""Which application is in the foreground (for diagnostics and per-app
compatibility settings; only the executable's file name is used), and
sending a key on to the app again (see SmartTextService, "hand back")."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Chromium/Electron applications: a page that re-renders its editor ends the
# composition but keeps showing it, and the next composition replaces it.
KEEP_APPS = frozenset({
    "msedge.exe", "chrome.exe", "brave.exe", "vivaldi.exe", "opera.exe", "msedgewebview2.exe",
    "code.exe", "cursor.exe", "windsurf.exe", "ms-teams.exe", "slack.exe", "discord.exe",
    "notion.exe", "obsidian.exe", "claude.exe", "chatgpt.exe", "figma.exe", "line.exe",
    "whatsapp.exe", "telegram.exe", "spotify.exe", "electron.exe",
})

if os.name == "nt":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                      ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]


_MOUSE_BUTTONS = (0x01, 0x02, 0x04)  # VK_LBUTTON, VK_RBUTTON, VK_MBUTTON

if os.name == "nt":
    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]

_KEYUP, _EXTENDED, _UNICODE = 0x0002, 0x0001, 0x0004
_MODIFIERS = ((0x11, "ctrl"), (0x10, "shift"))  # VK_CONTROL, VK_SHIFT (Alt combinations never reach an IME)
INJECTED_TAG = 0x534D4954  # same as engine.keys.INJECTED_TAG ("SMIT")


def send_key_again(vk: int, char: str, ctrl: bool, shift: bool, extended: bool) -> bool:
    """Type a key (with the modifiers it was pressed with) into the
    foreground app. A modifier the user still holds is left alone; one
    already released is pressed around the key, so a quick Ctrl+V never
    arrives as a plain "v". Text from other programs (VK_PACKET) is sent as
    the same Unicode character. Returns False if Windows refused (an
    elevated window, for example)."""
    if os.name != "nt" or os.environ.get("SMARTIME_NO_SENDINPUT"):
        return False  # (tests and simulators never type into the desktop)
    events: list[tuple[int, int, int]] = []  # (vk, scan, flags)
    if vk == 0xE7:  # VK_PACKET
        if not char:
            return False
        for flags in (_UNICODE, _UNICODE | _KEYUP):
            events.append((0, ord(char), flags))
    else:
        wanted = {"ctrl": ctrl, "shift": shift}
        around = [m for m, name in _MODIFIERS if wanted[name] and not (_user32.GetAsyncKeyState(m) & 0x8000)]
        ext = _EXTENDED if extended else 0
        scan = _user32.MapVirtualKeyW(vk, 0)
        events += [(m, _user32.MapVirtualKeyW(m, 0), 0) for m in around]
        events += [(vk, scan, ext), (vk, scan, ext | _KEYUP)]
        events += [(m, _user32.MapVirtualKeyW(m, 0), _KEYUP) for m in reversed(around)]
    arr = (_INPUT * len(events))()
    for i, (v, sc, flags) in enumerate(events):
        arr[i].type = 1  # INPUT_KEYBOARD
        arr[i].u.ki = _KEYBDINPUT(wVk=v, wScan=sc, dwFlags=flags, dwExtraInfo=INJECTED_TAG)
    return _user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT)) == len(events)


def foreground_elevated() -> bool:
    """Is the foreground window's process running as administrator? Our
    input would be blocked there (UIPI)."""
    if os.name != "nt":
        return False
    try:
        hwnd = _user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return True  # cannot even look at it: assume we cannot type there
        try:
            token = wintypes.HANDLE()
            if not _advapi32.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
                return True
            try:
                elevated = wintypes.DWORD()
                size = wintypes.DWORD()
                ok = _advapi32.GetTokenInformation(token, 20, ctypes.byref(elevated), 4, ctypes.byref(size))
                return bool(ok and elevated.value)  # TokenElevation
            finally:
                _kernel32.CloseHandle(token)
        finally:
            _kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return False


def mouse_clicked() -> bool:
    """Is a mouse button held now, or was one pressed since the previous
    call? (A quick click may be over before the app tells us about it.)"""
    if os.name != "nt":
        return False
    states = [_user32.GetAsyncKeyState(vk) for vk in _MOUSE_BUTTONS]  # query all: reading clears the bit
    return any(st & 0x8001 for st in states)


def foreground_app() -> str:
    """e.g. "Code.exe", "msedge.exe"; "" if it cannot be determined."""
    if os.name != "nt":
        return ""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return os.path.basename(buf.value)
        finally:
            _kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - diagnostics must never break typing
        return ""
