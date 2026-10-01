"""Which application is in the foreground (for diagnostics and per-app
compatibility settings). Only the executable's file name is used."""

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
