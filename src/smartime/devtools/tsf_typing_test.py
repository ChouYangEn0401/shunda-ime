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
from pathlib import Path
import time
from ctypes import wintypes

from ..engine.keys import INJECTED_TAG

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
ES_AUTOHSCROLL = 0x0080  # without it a single-line EDIT rejects text wider than the box
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000  # the caption must never take focus from the edit box
SM_CXSCREEN = 0
WM_SETFONT = 0x0030
EM_SETEDITSTYLE = 0x0400 + 204
SES_USECTF = 0x00010000
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_RETURN = 0x0D
PM_REMOVE = 1

NAMED_VK = {"ENTER": VK_RETURN, "BS": 0x08, "TAB": 0x09, "ESC": 0x1B, "LEFT": 0x25, "UP": 0x26,
            "RIGHT": 0x27, "DOWN": 0x28, "RSHIFT": 0xA1, "HOME": 0x24, "END": 0x23, "DEL": 0x2E,
            "RALT": 0xA5, "RCTRL": 0xA3}
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


# --- Never fight the user for the keyboard -------------------------------
# Low-level hooks tell our own SendInput events (injected *and* tagged with
# INJECTED_TAG) from everything else; a person typing through a remote-control
# tool (Quick Assist, ...) arrives as injected input too and must stop the test.
# from real ones; key codes are neither recorded nor blocked.
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
MOUSE_BUTTON_DOWN = {0x0201, 0x0204, 0x0207, 0x020B}  # L/R/M/X button down


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class UserGuard:
    """Detects physical keyboard/mouse-click input while the test runs."""

    def __init__(self) -> None:
        self.user_input = False
        self._kb = _HOOKPROC(self._on_key)
        self._ms = _HOOKPROC(self._on_mouse)
        self._hooks = [user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb, None, 0),
                       user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms, None, 0)]

    def _on_key(self, code, wparam, lparam):
        if code >= 0:
            k = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            if not (k.flags & LLKHF_INJECTED and k.dwExtraInfo == INJECTED_TAG):
                self.user_input = True
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_mouse(self, code, wparam, lparam):
        if code >= 0 and wparam in MOUSE_BUTTON_DOWN:
            m = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            if not (m.flags & LLMHF_INJECTED and m.dwExtraInfo == INJECTED_TAG):
                self.user_input = True
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def close(self) -> None:
        for h in self._hooks:
            if h:
                user32.UnhookWindowsHookEx(h)


def idle_seconds() -> float:
    info = _LASTINPUTINFO(cbSize=ctypes.sizeof(_LASTINPUTINFO))
    user32.GetLastInputInfo(ctypes.byref(info))
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def wait_until_idle(seconds: float = 5.0, timeout: float = 180.0) -> bool:
    """Wait until nobody has touched keyboard/mouse for ``seconds``."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if idle_seconds() >= seconds:
            return True
        time.sleep(0.25)
    return False


GUARD: UserGuard | None = None
PATIENCE = 30  # times a case is retried after the user touched the computer


def release_modifiers() -> None:
    """A stop between a modifier's down and up would leave it held for the
    user: send the key-ups (harmless if they are already up)."""
    for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, 0xA1, 0xA3, 0xA5):
        inp = INPUT(type=INPUT_KEYBOARD)
        flags = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if vk in (0xA3, 0xA5) else 0)
        inp.u.ki = KEYBDINPUT(wVk=vk, wScan=user32.MapVirtualKeyW(vk, 0), dwFlags=flags, dwExtraInfo=INJECTED_TAG)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


class TestWindow:
    """A caption line (what is being typed, what we expect) above a wide
    edit box. Wide enough that long cases stay readable while they run."""

    def __init__(self, richedit: bool = False) -> None:
        cls = "EDIT"
        if richedit:
            ctypes.WinDLL("msftedit")  # registers RICHEDIT50W
            cls = "RICHEDIT50W"
        hinst = kernel32.GetModuleHandleW(None)
        width = min(user32.GetSystemMetrics(SM_CXSCREEN) - 80, 1400)
        # Caption first, so creating it can't steal focus from the edit box.
        self.caption = user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, "STATIC", "",
                                              WS_POPUP | WS_VISIBLE | WS_BORDER, 40, 40, width, 90,
                                              None, None, hinst, None)
        self.hwnd = user32.CreateWindowExW(WS_EX_TOPMOST, cls, "", WS_POPUP | WS_VISIBLE | WS_BORDER | ES_AUTOHSCROLL,
                                           40, 134, width, 48, None, None, hinst, None)
        if not self.hwnd or not self.caption:
            raise OSError(f"CreateWindowEx failed ({ctypes.get_last_error()})")
        if richedit:
            # Make RichEdit talk to TSF directly instead of through IMM32.
            user32.SendMessageW(self.hwnd, EM_SETEDITSTYLE, SES_USECTF, SES_USECTF)
        font = gdi32.CreateFontW(-28, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft JhengHei UI")
        user32.SendMessageW(self.hwnd, WM_SETFONT, font, 1)
        small = gdi32.CreateFontW(-20, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft JhengHei UI")
        user32.SendMessageW(self.caption, WM_SETFONT, small, 1)

    def set_caption(self, text: str) -> None:
        user32.SetWindowTextW(self.caption, text)

    def focus(self) -> bool:
        """Windows' foreground lock only lets the process that produced the
        latest input switch windows; if the plain attempt fails, inject F24
        (a key no application uses) and try again."""
        for _ in range(4):
            if self._focus_once():
                return True
            for up in (False, True):
                inp = INPUT(type=INPUT_KEYBOARD)
                inp.u.ki = KEYBDINPUT(wVk=0x87, wScan=0, dwFlags=KEYEVENTF_KEYUP if up else 0,  # VK_F24
                                      dwExtraInfo=INJECTED_TAG)
                user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            pump(0.2)
        return False

    def _focus_once(self) -> bool:
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
        user32.DestroyWindow(self.caption)

    def _send(self, vk: int, up: bool) -> None:
        if GUARD is not None and GUARD.user_input:
            raise Aborted("you used the keyboard/mouse; stopped so we don't type over you")
        if user32.GetForegroundWindow() != self.hwnd:
            raise Aborted("test window lost the foreground; stopped sending keys")
        inp = INPUT(type=INPUT_KEYBOARD)
        flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in (0xA3, 0xA5) else 0)
        inp.u.ki = KEYBDINPUT(wVk=vk, wScan=user32.MapVirtualKeyW(vk, 0), dwFlags=flags, dwExtraInfo=INJECTED_TAG)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def tap(self, vk: int, shift: bool = False, ctrl: bool = False, alt: bool = False) -> None:
        tap_keys(self._send, vk, shift, ctrl, alt)


def tap_keys(send, vk: int, shift: bool = False, ctrl: bool = False, alt: bool = False) -> None:
    """Press and release one key with modifiers through ``send(vk, up)``."""
    if ctrl:
        send(VK_CONTROL, False)
    if alt:
        send(VK_MENU, False)
    if shift:
        send(VK_SHIFT, False)
    send(vk, False)
    send(vk, True)
    if shift:
        send(VK_SHIFT, True)
    if alt:
        send(VK_MENU, True)
    if ctrl:
        send(VK_CONTROL, True)
    pump(0.06)


def type_script(tap, script: str) -> None:
    """Type a key script (simulator syntax) with ``tap(vk, shift, ctrl)``."""
    i = 0
    while i < len(script):
        if script[i] == "{":
            name = script[i + 1:script.index("}", i)]
            if name.startswith(("C-", "CS-", "CA-")):
                mods, base = name.split("-", 1)
                vk = NAMED_VK.get(base) or OEM_VK.get(base, ord(base.upper()))
                tap(vk, mods == "CS", True, mods == "CA")
            elif name == "S-TAB":
                tap(0x09, True, False)
            else:
                tap(NAMED_VK[name], False, False)
                if name in ("RSHIFT", "RALT", "RCTRL"):
                    pump(0.1)
            i += len(name) + 2
            continue
        ch = script[i]
        shift = ch in SHIFTED
        base = SHIFTED.get(ch, ch)
        tap(OEM_VK.get(base, ord(base.upper())), shift, False)
        i += 1


# (script, expected). expected=None means "whatever the engine simulator
# produces for the same keys": the real app must behave exactly like the
# simulation (this is what catches TSF/PIME integration bugs). A tuple means
# any of those texts is right — the candidate order depends on what this
# machine's dictionary has learned, and the test reads the real one.
CASES = [
    ("ji3ap7{ENTER}", "我們"),  # first syllable must convert too (regression)
    # clause punctuation sends the sentence; the mark itself stays in the
    # composition (so ↓ can still change its width), hence the Enter
    ("su3cl3{C-.}{ENTER}", "你好。"),
    ("su3cl3<{ENTER}", "你好<"),  # Shift+, types what is on the key (punct_style "keycap")
    ("mvp {ENTER}", "mvp "),
    ("ji3m/4python vu,3{ENTER}", "我用python 寫"),
    ("ji3ap7{BS}{ENTER}", "我"),  # backspace removes a whole syllable
    # candidate for the char after the cursor. 嗎/嘛 swap places once one of
    # them is learned, so this checks that *a* different character arrived,
    # not which one — the real dictionary is the user's, and it moves.
    ("ji3a87{LEFT}{UP}2{ENTER}", ("我嘛", "我嗎")),
    ("ao6u.3{TAB}{ENTER}", "沒有用"),  # Tab completion
    # lone right Shift taps cycle 自動 -> 純注音 -> 純英文 -> 自動 (the default)
    ("{RSHIFT}{RSHIFT}abc{RSHIFT}ji3{ENTER}", "abc我"),
    ("k27{ENTER}", "的"),  # keys out of order (fast typing)
    ("2; ji3rup wu0 t;6g4283{ENTER}", "當我今天嘗試打"),  # 283 is 打, not a number
    # Ctrl+, types the full-width comma and sends the sentence; the mark
    # itself stays in the composition so its width is still changeable, so
    # the test has to commit before reading the field.
    ("su3cl3{C-,}{ENTER}", "你好，"),
    ("{C-[}ji3{C-]}{ENTER}", "「我」"),
    ("cl3dj4i {ENTER}", "好酷喔"),  # i␣ is ㄛ (喔), not the word "i"
    ("ji3ee/4dj94{ENTER}", "我更快"),  # stray key left by fast typing is dropped
    ("mvp {DOWN}4{ENTER}", "勳"),  # English token -> Chinese reading (␣ is its tone key)
    ('ji3ap7"python"{ENTER}', '我們"python"'),  # " stays half-width
    ("ji3a87{ESC}j{ENTER}", ("我嘛", "我嗎")),  # correction mode: j swaps the candidate in place
    ("mvp {ESC}e{ENTER}", "勳"),  # correction mode: e turns raw keys into Chinese
    ("ji3ee/4dj94{ESC}vv{HOME}lllxv{ENTER}", "我更快"),  # 按鍵 view: delete one stray key
    ("ji3{RCTRL}{TAB}{TAB}1{ENTER}", "我α"),  # symbol panel: a lone right-Ctrl tap
    ("{RCTRL}{TAB}{TAB}2", "β"),  # symbol panel with nothing composed: typed directly
    ("ao6u.3{S-TAB}3{ENTER}", None),  # Shift+Tab: all continuations
    # > 30 characters: automatic partial commit mid-sentence (broke in VS Code)
    ("b06c.4283tj x96k27y4b/6b06j6z83fm4u/ jp6k27jp4wu6ru.4cjo4y94vscodexu3ua04yjo4284k27t8 u4{ENTER}", None),
    # Ctrl+V while composing: commit first, then the app pastes after the text
    # (the clipboard holds PASTE_TEXT during these cases)
    ("ji3ap7{C-v}", "我們XYZ"),
    ("ji3{C-v}ap7{ENTER}", "我XYZ們"),
    # other keys for the app, same rule (no clipboard needed): Ctrl+A selects
    # everything after 我 is committed, so 們 replaces it; Ctrl+← moves the
    # caret to the start after the commit
    ("ji3{C-a}ap7{ENTER}", "們"),
    ("ji3{C-LEFT}ap7{ENTER}", "們我"),
]
PASTE_TEXT = "XYZ"


def expected_text(script: str) -> str:
    """What the engine produces for ``script`` with the settings the real IME
    uses during the test (defaults, learning off) and a *copy* of the user's
    memory — the real IME ranks with it too (it once typed 的字 where an
    empty memory gives 的自). Computed in a throwaway folder, so the real one
    is never touched."""
    import os
    import sqlite3
    import tempfile

    from .. import paths
    from ..engine.session import Session
    from ..pime.server import build_engine
    from .simulate import run

    real_db = paths.user_db_path()
    old = os.environ.get("SMARTIME_USER_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        if real_db.exists():
            src = sqlite3.connect(f"file:{real_db.as_posix()}?mode=ro", uri=True)
            dst = sqlite3.connect(Path(tmp) / "user.db")
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
        os.environ["SMARTIME_USER_DIR"] = tmp
        try:
            engine = build_engine()
            engine.config.learn = False
            out, view = run(Session(engine), script.replace("{RSHIFT}", "{SHIFT}"))
            engine.lexicon.user.close()
            engine.lexicon.close()
        finally:
            if old is None:
                os.environ.pop("SMARTIME_USER_DIR", None)
            else:
                os.environ["SMARTIME_USER_DIR"] = old
    return out + view.composition


class MemoryGuard:
    """The real IME would learn from the test sentences. While the test runs
    it uses default settings with learning turned off, so the user's memory
    is never touched (it used to be rewound to a backup, which also threw
    away whatever the user taught it while the test was waiting for them).
    Settings and recent symbols are put back afterwards (also on abort)."""

    def __init__(self) -> None:
        from .. import paths
        from ..config import Config

        self.files = {}
        for f in (paths.config_path(), paths.user_dir() / "recent-symbols.json"):
            self.files[f] = f.read_bytes() if f.exists() else None
        cfg = Config()
        cfg.learn = False
        cfg.save(paths.config_path())  # defaults, no learning, while testing

    def rewind(self) -> None:
        """Between cases: nothing to undo (learning is off)."""

    def restore(self) -> None:
        for f, data in self.files.items():
            if data is None:
                f.unlink(missing_ok=True)
            else:
                f.write_bytes(data)


class ClipboardGuard:
    """Paste cases need known clipboard text. Only used when the clipboard
    holds nothing or plain text (which is put back afterwards); with an
    image or files on it, the paste cases are skipped instead."""

    CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT, CF_LOCALE = 1, 7, 13, 16

    def __init__(self) -> None:
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.k32.GlobalAlloc.restype = ctypes.c_void_p
        self.k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self.k32.GlobalLock.restype = ctypes.c_void_p
        self.k32.GlobalLock.argtypes = [ctypes.c_void_p]
        self.k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self.u32.GetClipboardData.restype = ctypes.c_void_p
        self.u32.SetClipboardData.restype = ctypes.c_void_p
        self.u32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
        self.u32.EnumClipboardFormats.argtypes = [wintypes.UINT]
        self.usable = False
        self.saved: str | None = None
        if not self._open():
            return
        try:
            fmts, f = [], 0
            while True:
                f = self.u32.EnumClipboardFormats(f)
                if not f:
                    break
                fmts.append(f)
            if all(x in (self.CF_TEXT, self.CF_OEMTEXT, self.CF_UNICODETEXT, self.CF_LOCALE) for x in fmts):
                self.usable = True
                h = self.u32.GetClipboardData(self.CF_UNICODETEXT)
                if h:
                    ptr = self.k32.GlobalLock(h)
                    self.saved = ctypes.wstring_at(ptr)
                    self.k32.GlobalUnlock(h)
        finally:
            self.u32.CloseClipboard()

    def _open(self) -> bool:
        for _ in range(10):
            if self.u32.OpenClipboard(None):
                return True
            time.sleep(0.05)
        return False

    def set(self, text: str | None) -> None:
        if not self._open():
            return
        try:
            self.u32.EmptyClipboard()
            if text is not None:
                data = text.encode("utf-16-le") + b"\0\0"
                h = self.k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
                ptr = self.k32.GlobalLock(h)
                ctypes.memmove(ptr, data, len(data))
                self.k32.GlobalUnlock(h)
                self.u32.SetClipboardData(self.CF_UNICODETEXT, h)
        finally:
            self.u32.CloseClipboard()

    def restore(self) -> None:
        if self.usable:
            self.set(self.saved)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    global GUARD
    richedit = "--richedit" in sys.argv[1:]
    cases = [(s, e if e is not None else expected_text(s)) for s, e in CASES]
    print("waiting until keyboard/mouse have been idle for 5 s ...")
    if not wait_until_idle():
        print("ABORT: the computer is in use; try again later (no keys were sent)")
        return 2
    memory = MemoryGuard()
    clipboard = ClipboardGuard()
    ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    mgr = ProfileMgr()
    previous = mgr.active()
    GUARD = UserGuard()
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
        for n, (script, expected) in enumerate(cases, 1):
            if "{C-v}" in script:
                if not clipboard.usable:
                    print(f"SKIP  {script!r:36} (the clipboard holds an image/files; not touched)")
                    continue
                clipboard.set(PASTE_TEXT)
            def restart_ime() -> None:
                # the mode and any composition live on in the IME: start afresh
                mgr.activate(previous.dwProfileType, previous.langid, previous.clsid, previous.guidProfile,
                             previous.hkl, TF_IPPMF_FORPROCESS | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
                pump(0.3)
                mgr.activate(TF_PROFILETYPE_INPUTPROCESSOR, 0x0404, guid(PIME_CLSID), guid(PROFILE_GUID), None,
                             TF_IPPMF_FORPROCESS | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
                pump(0.8)

            for attempt in range(PATIENCE + 1):
                try:
                    memory.rewind()
                    win.set_caption(f"  順打輸入法自動測試 {n}/{len(cases)}（碰鍵盤或滑鼠會立即停止）\r\n"
                                    f"  按鍵：{script}\r\n  預期：{expected}")
                    win.clear()
                    pump(0.1)
                    type_script(win.tap, script)
                    pump(0.3)
                    got = win.text()
                    break
                except Aborted as e:
                    # Someone used the computer: let go of everything, wait
                    # until they stop, and try this case again from scratch.
                    release_modifiers()
                    if attempt == PATIENCE:
                        raise
                    print(f"PAUSE ({e}); waiting until the computer is idle again ...")
                    if not wait_until_idle(timeout=900):
                        raise
                    GUARD.user_input = False
                    if not win.focus():
                        raise Aborted("could not bring the test window back to the foreground") from e
                    restart_ime()
            if "SHIFT}" in script:
                restart_ime()
            # a tuple of expectations means "any of these" — for cases whose
            # candidate order depends on what this machine's dictionary has
            # learned (the test reads the user's real memory)
            ok = got in expected if isinstance(expected, tuple) else got == expected
            failures += not ok
            label = script if len(script) <= 34 else script[:31] + "..."
            print(f"{'PASS' if ok else 'FAIL'}  {label!r:36} -> {got!r}" + ("" if ok else f"  (expected {expected!r})"))
        return 1 if failures else 0
    except Aborted as e:
        release_modifiers()
        print("ABORT:", e)
        return 2
    finally:
        mgr.activate(previous.dwProfileType, previous.langid, previous.clsid, previous.guidProfile,
                     previous.hkl, TF_IPPMF_FORPROCESS | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        win.destroy()
        GUARD.close()
        memory.restore()
        clipboard.restore()
        pump(0.1)


if __name__ == "__main__":
    sys.exit(main())
