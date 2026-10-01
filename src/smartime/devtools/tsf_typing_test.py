"""Real typing test: a Win32 EDIT control + our IME activated through TSF.

Unlike pime_probe (which talks to the launcher directly), this goes through
the full stack an application sees: SendInput -> TSF -> PIMETextService.dll
-> PIMELauncher -> our backend -> composition/commit back into the control.

Safety: keystrokes are synthesized with SendInput, which targets the
foreground window. The test only sends a key after confirming that its own
window is in the foreground, and aborts otherwise. The previously active
input method is restored afterwards.

    python -m smartime.devtools.tsf_typing_test               # classic EDIT (IMM/CUAS path)
    python -m smartime.devtools.tsf_typing_test --richedit    # RichEdit with TSF (Notepad/Office-like)
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")
kernel32 = ctypes.WinDLL("kernel32")

PIME_CLSID = "{35F67E9D-A54D-4177-9697-8B0AB71A9E04}"
PROFILE_GUID = "{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}"
CLSID_TF_InputProcessorProfiles = "{33C53A50-F456-4884-B049-85FD643ECFED}"
IID_ITfInputProcessorProfileMgr = "{71C6E74C-0F28-11D8-A82A-00065B84435C}"
GUID_TFCAT_TIP_KEYBOARD = "{34745C63-B2F0-4784-8B67-5E12C8701A31}"

TF_PROFILETYPE_INPUTPROCESSOR = 1
TF_IPPMF_FORPROCESS = 0x10000000
TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE = 0x4

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_BORDER = 0x00800000
WS_EX_TOPMOST = 0x00000008
WM_SETFONT = 0x0030
EM_SETEDITSTYLE = 0x0400 + 204
SES_USECTF = 0x00010000
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_SHIFT = 0x10
VK_RETURN = 0x0D
PM_REMOVE = 1

NAMED_VK = {"ENTER": VK_RETURN, "BS": 0x08, "TAB": 0x09, "ESC": 0x1B, "LEFT": 0x25, "UP": 0x26,
            "RIGHT": 0x27, "DOWN": 0x28, "RSHIFT": 0xA1}
OEM_VK = {" ": 0x20, ",": 0xBC, ".": 0xBE, "/": 0xBF, ";": 0xBA, "-": 0xBD, "'": 0xDE, "[": 0xDB, "]": 0xDD}
SHIFTED = {"<": ",", ">": ".", "?": "/", ":": ";", '"': "'", "{": "[", "}": "]"}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


def guid(s: str) -> GUID:
    g = GUID()
    if ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g)) != 0:
        raise ValueError(s)
    return g


class TF_INPUTPROCESSORPROFILE(ctypes.Structure):
    _fields_ = [("dwProfileType", wintypes.DWORD), ("langid", wintypes.WORD), ("clsid", GUID),
                ("guidProfile", GUID), ("catid", GUID), ("hklSubstitute", wintypes.HKL),
                ("dwCaps", wintypes.DWORD), ("hkl", wintypes.HKL), ("dwFlags", wintypes.DWORD)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
gdi32 = ctypes.WinDLL("gdi32")
gdi32.CreateFontW.restype = wintypes.HFONT


def vcall(obj: ctypes.c_void_p, index: int, argtypes: list, *args) -> int:
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn(obj, *args)


class ProfileMgr:
    """Minimal ITfInputProcessorProfileMgr (vtable order from msctf.idl)."""

    ACTIVATE, GET_ACTIVE = 3, 10

    def __init__(self) -> None:
        self.ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(guid(CLSID_TF_InputProcessorProfiles)), None, 1,
                                    ctypes.byref(guid(IID_ITfInputProcessorProfileMgr)), ctypes.byref(self.ptr))
        if hr != 0:
            raise OSError(f"CoCreateInstance failed: {hr & 0xFFFFFFFF:#x}")

    def active(self) -> TF_INPUTPROCESSORPROFILE:
        p = TF_INPUTPROCESSORPROFILE()
        vcall(self.ptr, self.GET_ACTIVE, [ctypes.POINTER(GUID), ctypes.POINTER(TF_INPUTPROCESSORPROFILE)],
              ctypes.byref(guid(GUID_TFCAT_TIP_KEYBOARD)), ctypes.byref(p))
        return p

    def activate(self, ptype, langid, clsid: GUID, profile: GUID, hkl, flags) -> int:
        return vcall(self.ptr, self.ACTIVATE,
                     [wintypes.DWORD, wintypes.WORD, ctypes.POINTER(GUID), ctypes.POINTER(GUID), wintypes.HKL,
                      wintypes.DWORD],
                     ptype, langid, ctypes.byref(clsid), ctypes.byref(profile), hkl, flags)


def pump(seconds: float) -> None:
    msg = wintypes.MSG()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)


class Aborted(Exception):
    pass


class TestWindow:
    def __init__(self, richedit: bool = False) -> None:
        cls = "EDIT"
        if richedit:
            ctypes.WinDLL("msftedit")  # registers RICHEDIT50W
            cls = "RICHEDIT50W"
        self.hwnd = user32.CreateWindowExW(WS_EX_TOPMOST, cls, "", WS_POPUP | WS_VISIBLE | WS_BORDER,
                                           40, 40, 520, 48, None, None, kernel32.GetModuleHandleW(None), None)
        if not self.hwnd:
            raise OSError(f"CreateWindowEx failed ({ctypes.get_last_error()})")
        if richedit:
            # Make RichEdit talk to TSF directly instead of through IMM32.
            user32.SendMessageW(self.hwnd, EM_SETEDITSTYLE, SES_USECTF, SES_USECTF)
        font = gdi32.CreateFontW(-28, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft JhengHei UI")
        user32.SendMessageW(self.hwnd, WM_SETFONT, font, 1)

    def focus(self) -> bool:
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None)
        me = kernel32.GetCurrentThreadId()
        attached = fg_thread and fg_thread != me and user32.AttachThreadInput(fg_thread, me, True)
        user32.BringWindowToTop(self.hwnd)
        user32.SetForegroundWindow(self.hwnd)
        user32.SetFocus(self.hwnd)
        if attached:
            user32.AttachThreadInput(fg_thread, me, False)
        pump(0.2)
        return user32.GetForegroundWindow() == self.hwnd

    def text(self) -> str:
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(self.hwnd, buf, 512)
        return buf.value

    def clear(self) -> None:
        user32.SetWindowTextW(self.hwnd, "")

    def destroy(self) -> None:
        user32.DestroyWindow(self.hwnd)

    def _send(self, vk: int, up: bool) -> None:
        if user32.GetForegroundWindow() != self.hwnd:
            raise Aborted("test window lost the foreground; stopped sending keys")
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(wVk=vk, wScan=user32.MapVirtualKeyW(vk, 0), dwFlags=KEYEVENTF_KEYUP if up else 0)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def tap(self, vk: int, shift: bool = False) -> None:
        if shift:
            self._send(VK_SHIFT, False)
        self._send(vk, False)
        self._send(vk, True)
        if shift:
            self._send(VK_SHIFT, True)
        pump(0.06)

    def type(self, script: str) -> None:
        i = 0
        while i < len(script):
            if script[i] == "{":
                name = script[i + 1:script.index("}", i)]
                self.tap(NAMED_VK[name])
                if name == "RSHIFT":
                    pump(0.1)
                i += len(name) + 2
                continue
            ch = script[i]
            shift = ch in SHIFTED
            base = SHIFTED.get(ch, ch)
            vk = OEM_VK.get(base, ord(base.upper()))
            self.tap(vk, shift)
            i += 1


CASES = [
    ("ji3ap7{ENTER}", "我們"),  # first syllable must convert too (regression)
    ("su3cl3<", "你好，"),  # clause punctuation commits
    ("mvp {ENTER}", "mvp "),
    ("ji3m/4python vu,3{ENTER}", "我用python 寫"),
    ("ji3ap7{BS}{ENTER}", "我"),  # backspace removes a whole syllable
    ("ji3a87{LEFT}{UP}2{ENTER}", "我嘛"),  # candidate for the char after the cursor
    ("ao6u.3{TAB}{ENTER}", "沒有用"),  # Tab completion
    ("{RSHIFT}abc{RSHIFT}ji3{ENTER}", "abc我"),  # lone right Shift toggles English
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    richedit = "--richedit" in sys.argv[1:]
    ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    mgr = ProfileMgr()
    previous = mgr.active()
    win = TestWindow(richedit)
    print('control:', 'RichEdit (TSF)' if richedit else 'EDIT (IMM/CUAS)')
    failures = 0
    try:
        if not win.focus():
            print("ABORT: could not bring the test window to the foreground; no keys were sent")
            return 2
        hr = mgr.activate(TF_PROFILETYPE_INPUTPROCESSOR, 0x0404, guid(PIME_CLSID), guid(PROFILE_GUID), None,
                          TF_IPPMF_FORPROCESS | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        if hr != 0:
            print(f"FAIL: ActivateProfile returned {hr & 0xFFFFFFFF:#x}")
            return 1
        pump(0.8)  # let TSF load PIMETextService.dll and connect to the launcher
        for script, expected in CASES:
            win.clear()
            pump(0.1)
            win.type(script)
            pump(0.3)
            got = win.text()
            ok = got == expected
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {script!r:30} -> {got!r}  (expected {expected!r})")
        return 1 if failures else 0
    except Aborted as e:
        print("ABORT:", e)
        return 2
    finally:
        mgr.activate(previous.dwProfileType, previous.langid, previous.clsid, previous.guidProfile,
                     previous.hkl, TF_IPPMF_FORPROCESS | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        win.destroy()
        pump(0.1)


if __name__ == "__main__":
    sys.exit(main())
