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
VK_DELETE = 0x2E
VK_NUMPAD0 = 0x60
VK_DIVIDE = 0x6F
VK_NUMLOCK = 0x90
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

SCAN_LSHIFT = 0x2A
SCAN_RSHIFT = 0x36


@dataclass(frozen=True)
class KeyInput:
    vk: int
    char: str = ""  # character produced by the key with current modifiers
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    caps: bool = False  # Caps Lock toggled on
    scan: int = 0

    @property
    def numpad(self) -> bool:
        return VK_NUMPAD0 <= self.vk <= VK_DIVIDE

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
