"""Platform-neutral key events (values follow Windows virtual-key codes)."""

from __future__ import annotations

from dataclasses import dataclass

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_CLEAR = 0x0C  # the numeric keypad's 5 with NumLock off
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_NUMPAD0 = 0x60
VK_NUMPAD9 = 0x69
VK_DIVIDE = 0x6F
VK_NUMLOCK = 0x90
VK_PACKET = 0xE7  # a Unicode character sent by a program (voice input, paste tools)
VK_OEM_1 = 0xBA  # ;
VK_OEM_COMMA = 0xBC
VK_OEM_MINUS = 0xBD
VK_OEM_PERIOD = 0xBE
VK_OEM_2 = 0xBF  # /
VK_OEM_4 = 0xDB  # [
VK_OEM_6 = 0xDD  # ]
VK_OEM_7 = 0xDE  # '
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

MODIFIER_VKS = frozenset(
    {VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL, VK_NUMLOCK, VK_LSHIFT, VK_RSHIFT,
     VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU}
)

# dwExtraInfo on every input event SmartIME sends itself with SendInput (voice
# typing, the real-app tests), so hooks can tell it from anyone else's input,
# including other programs' injected input (remote control, macro tools).
INJECTED_TAG = 0x534D4954  # "SMIT"

SCAN_LSHIFT = 0x2A
SCAN_RSHIFT = 0x36

# With NumLock off the numeric keypad sends navigation keys instead of digits.
# They arrive *non-extended*, while the dedicated Insert/Home/End/arrow block
# is extended, so the two can still be told apart — which matters because
# PIME's KeyEvent::scanCode() is broken (it forgets to shift lParam right by
# 16 and so always returns 0), leaving isExtended as the only signal.
NUMPAD_NAV_DIGIT = {
    VK_INSERT: "0", VK_END: "1", VK_DOWN: "2", VK_NEXT: "3", VK_LEFT: "4",
    VK_CLEAR: "5", VK_RIGHT: "6", VK_HOME: "7", VK_UP: "8", VK_PRIOR: "9",
}


@dataclass(frozen=True)
class KeyInput:
    vk: int
    char: str = ""  # character produced by the key with current modifiers
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    caps: bool = False  # Caps Lock toggled on
    scan: int = 0
    extended: bool = False  # right-hand Alt/Ctrl, arrows, ... (PIME isExtended)

    @property
    def numpad(self) -> bool:
        return VK_NUMPAD0 <= self.vk <= VK_DIVIDE

    @property
    def digit(self) -> str:
        """``"0"``–``"9"`` for the top row and for the numeric keypad, whether
        or not NumLock is on; ``""`` for any other key.

        Selecting a candidate with the keypad must work either way: with
        NumLock off the keypad sends Insert/End/↓/PageDown…, and dropping
        those on the floor closed the candidate window and typed into the
        document instead.
        """
        if len(self.char) == 1 and self.char in "0123456789":
            return self.char
        if VK_NUMPAD0 <= self.vk <= VK_NUMPAD9:
            return chr(ord("0") + self.vk - VK_NUMPAD0)
        if not self.extended:
            return NUMPAD_NAV_DIGIT.get(self.vk, "")
        return ""

    @property
    def printable(self) -> bool:
        return len(self.char) == 1 and self.char.isprintable()

    @classmethod
    def from_char(cls, ch: str) -> KeyInput:
        """Convenience for tests/simulators: a key that types ``ch``."""
        special = {" ": VK_SPACE}
        vk = special.get(ch, ord(ch.upper()) if ch.isalnum() else 0)
        shift = ch.isupper() or ch in '<>?:"{}|~!@#$%^&*()_+'
        return cls(vk=vk, char=ch, shift=shift)
