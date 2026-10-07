"""ctypes declarations for the on-screen panels (user32, gdi32, dwmapi).

Only what smartime.ui needs; every function gets explicit argtypes/restype
so handles survive on 64-bit Python.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

if os.name != "nt":  # pragma: no cover - the panels exist on Windows only
    raise ImportError("smartime.ui needs Windows")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:  # pragma: no cover
    dwmapi = None

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

# messages / styles / flags
WM_DESTROY, WM_PAINT, WM_ERASEBKGND, WM_TIMER = 0x0002, 0x000F, 0x0014, 0x0113
WM_NCHITTEST, WM_MOUSEACTIVATE, WM_APP, WM_QUIT = 0x0084, 0x0021, 0x8000, 0x0012
HTTRANSPARENT, MA_NOACTIVATE = -1, 3
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TRANSPARENT = 0x8, 0x80, 0x08000000, 0x20
WS_EX_LAYERED = 0x00080000
GWL_EXSTYLE = -20
LWA_ALPHA = 0x2
CS_DROPSHADOW = 0x00020000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_NOZORDER = 0x0010, 0x0040, 0x0004
HWND_TOPMOST = wintypes.HWND(-1)
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUNDSMALL = 33, 3
DWMWA_BORDER_COLOR = 34
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
MONITOR_DEFAULTTONEAREST = 2
TRANSPARENT = 1
DIB_RGB_COLORS, BI_RGB, SRCCOPY = 0, 0, 0x00CC0020
CLEARTYPE_QUALITY, DEFAULT_CHARSET = 5, 1
PS_SOLID, NULL_BRUSH, NULL_PEN = 0, 5, 8
ETO_CLIPPED = 4


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class TEXTMETRICW(ctypes.Structure):
    _fields_ = [("tmHeight", wintypes.LONG), ("tmAscent", wintypes.LONG), ("tmDescent", wintypes.LONG),
                ("tmInternalLeading", wintypes.LONG), ("tmExternalLeading", wintypes.LONG),
                ("tmAveCharWidth", wintypes.LONG), ("tmMaxCharWidth", wintypes.LONG), ("tmWeight", wintypes.LONG),
                ("tmOverhang", wintypes.LONG), ("tmDigitizedAspectX", wintypes.LONG),
                ("tmDigitizedAspectY", wintypes.LONG), ("tmFirstChar", wintypes.WCHAR), ("tmLastChar", wintypes.WCHAR),
                ("tmDefaultChar", wintypes.WCHAR), ("tmBreakChar", wintypes.WCHAR), ("tmItalic", wintypes.BYTE),
                ("tmUnderlined", wintypes.BYTE), ("tmStruckOut", wintypes.BYTE), ("tmPitchAndFamily", wintypes.BYTE),
                ("tmCharSet", wintypes.BYTE)]


def _decl(lib, name, restype, *argtypes):
    fn = getattr(lib, name)
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


H = wintypes.HANDLE
_decl(user32, "RegisterClassExW", wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
_decl(user32, "CreateWindowExW", wintypes.HWND, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE,
      wintypes.LPVOID)
_decl(user32, "DefWindowProcW", LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_decl(user32, "DestroyWindow", wintypes.BOOL, wintypes.HWND)
_decl(user32, "ShowWindow", wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_decl(user32, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)
_decl(user32, "IsWindow", wintypes.BOOL, wintypes.HWND)
_decl(user32, "SetWindowPos", wintypes.BOOL, wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      ctypes.c_int, wintypes.UINT)
_decl(user32, "GetWindowRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
_decl(user32, "FindWindowExW", wintypes.HWND, wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
_decl(user32, "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_decl(user32, "GetForegroundWindow", wintypes.HWND)
_decl(user32, "GetGUIThreadInfo", wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(GUITHREADINFO))
_decl(user32, "ClientToScreen", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.POINT))
_decl(user32, "BeginPaint", wintypes.HDC, wintypes.HWND, ctypes.POINTER(PAINTSTRUCT))
_decl(user32, "EndPaint", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(PAINTSTRUCT))
_decl(user32, "InvalidateRect", wintypes.BOOL, wintypes.HWND, ctypes.c_void_p, wintypes.BOOL)
_decl(user32, "GetDC", wintypes.HDC, wintypes.HWND)
_decl(user32, "ReleaseDC", ctypes.c_int, wintypes.HWND, wintypes.HDC)
_decl(user32, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_decl(user32, "SetTimer", ctypes.c_size_t, wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p)
_decl(user32, "KillTimer", wintypes.BOOL, wintypes.HWND, ctypes.c_size_t)
_decl(user32, "GetMessageW", wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_decl(user32, "TranslateMessage", wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
_decl(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(wintypes.MSG))
_decl(user32, "PostThreadMessageW", wintypes.BOOL, wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_decl(user32, "MonitorFromRect", H, ctypes.POINTER(wintypes.RECT), wintypes.DWORD)
_decl(user32, "GetMonitorInfoW", wintypes.BOOL, H, ctypes.POINTER(MONITORINFO))
_decl(user32, "GetDpiForWindow", wintypes.UINT, wintypes.HWND)
_decl(user32, "FillRect", ctypes.c_int, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH)
# Making another process's window fully transparent (PIME's hint box, which we
# keep alive only as an anchor): style changes other than GWLP_WNDPROC are
# allowed across processes, and LWA_ALPHA needs no access to its DC.
_decl(user32, "GetWindowLongW", wintypes.LONG, wintypes.HWND, ctypes.c_int)
_decl(user32, "SetWindowLongW", wintypes.LONG, wintypes.HWND, ctypes.c_int, wintypes.LONG)
_decl(user32, "SetLayeredWindowAttributes", wintypes.BOOL, wintypes.HWND, wintypes.COLORREF,
      wintypes.BYTE, wintypes.DWORD)
try:
    _decl(user32, "SetThreadDpiAwarenessContext", ctypes.c_void_p, ctypes.c_void_p)
except AttributeError:  # pragma: no cover - before Windows 10 1607
    pass
try:
    shcore = ctypes.WinDLL("shcore")
    _decl(shcore, "GetDpiForMonitor", ctypes.c_long, H, ctypes.c_int, ctypes.POINTER(wintypes.UINT),
          ctypes.POINTER(wintypes.UINT))
except (OSError, AttributeError):  # pragma: no cover
    shcore = None

_decl(gdi32, "CreateCompatibleDC", wintypes.HDC, wintypes.HDC)
_decl(gdi32, "CreateDIBSection", wintypes.HBITMAP, wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
      ctypes.POINTER(ctypes.c_void_p), H, wintypes.DWORD)
_decl(gdi32, "SelectObject", H, wintypes.HDC, H)
_decl(gdi32, "DeleteObject", wintypes.BOOL, H)
_decl(gdi32, "DeleteDC", wintypes.BOOL, wintypes.HDC)
_decl(gdi32, "BitBlt", wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD)
_decl(gdi32, "CreateFontW", wintypes.HFONT, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
      wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR)
_decl(gdi32, "SetBkMode", ctypes.c_int, wintypes.HDC, ctypes.c_int)
_decl(gdi32, "SetTextColor", wintypes.COLORREF, wintypes.HDC, wintypes.COLORREF)
_decl(gdi32, "ExtTextOutW", wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.UINT,
      ctypes.POINTER(wintypes.RECT), wintypes.LPCWSTR, wintypes.UINT, ctypes.c_void_p)
_decl(gdi32, "GetTextMetricsW", wintypes.BOOL, wintypes.HDC, ctypes.POINTER(TEXTMETRICW))
_decl(gdi32, "GetTextExtentPoint32W", wintypes.BOOL, wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(SIZE))
_decl(gdi32, "CreateSolidBrush", wintypes.HBRUSH, wintypes.COLORREF)
_decl(gdi32, "CreatePen", wintypes.HPEN, ctypes.c_int, ctypes.c_int, wintypes.COLORREF)
_decl(gdi32, "GetStockObject", H, ctypes.c_int)
_decl(gdi32, "RoundRect", wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      ctypes.c_int, ctypes.c_int)
_decl(gdi32, "MoveToEx", wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
_decl(gdi32, "LineTo", wintypes.BOOL, wintypes.HDC, ctypes.c_int, ctypes.c_int)
_decl(kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
_decl(kernel32, "GetCurrentThreadId", wintypes.DWORD)
if dwmapi is not None:
    _decl(dwmapi, "DwmSetWindowAttribute", ctypes.c_long, wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
          wintypes.DWORD)


def rgb(color: int) -> int:
    """0xRRGGBB -> COLORREF (0x00BBGGRR)."""
    return ((color & 0xFF) << 16) | (color & 0xFF00) | ((color >> 16) & 0xFF)
