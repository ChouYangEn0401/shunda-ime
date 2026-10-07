"""Type a key script into a Session without installing the IME.

Key script syntax: plain characters are typed as-is (``ji3`` = ㄨㄛˇ); named
keys go in braces: {BS} {DEL} {ENTER} {ESC} {TAB} {LEFT} {RIGHT} {UP} {DOWN}
{HOME} {END} {NUM1}..{NUM9} (numeric keypad, NumLock on) {KP1}..{KP9} (the
same keys with NumLock off) {SHIFT} (a lone Shift tap), {RCTRL} / {RALT} (a lone right-Ctrl /
right-Alt tap: the symbol panel),
{SPACE}, {S-TAB} (Shift+Tab), {S-LEFT}/{S-RIGHT} etc. ({PGUP} {PGDN} too).
Ctrl combinations: {C-,} {C-d}; Ctrl+Shift: {CS-/}; Ctrl+Alt: {CA-,}.

    python -m smartime.devtools.simulate "ji3ap7{DOWN}"
    python -m smartime.devtools.simulate --steps "su3cl3<"
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
import tempfile
from collections.abc import Iterator

from ..engine.keys import (
    SCAN_RSHIFT, VK_BACK, VK_CLEAR, VK_DELETE, VK_DOWN, VK_END, VK_ESCAPE, VK_HOME, VK_INSERT,
    VK_LEFT, VK_NEXT, VK_NUMPAD0, VK_OEM_1, VK_OEM_2, VK_OEM_4, VK_OEM_6, VK_OEM_7,
    VK_OEM_COMMA, VK_OEM_MINUS, VK_OEM_PERIOD, VK_PRIOR, VK_RETURN,
    VK_CONTROL, VK_MENU, VK_RIGHT, VK_SHIFT, VK_SPACE, VK_TAB, VK_UP, KeyInput,
)
from ..engine.session import Session, View

NAMED = {
    "BS": VK_BACK, "DEL": VK_DELETE, "ENTER": VK_RETURN, "ESC": VK_ESCAPE, "TAB": VK_TAB,
    "LEFT": VK_LEFT, "RIGHT": VK_RIGHT, "UP": VK_UP, "DOWN": VK_DOWN, "HOME": VK_HOME,
    "END": VK_END, "SPACE": VK_SPACE,
    # the numeric keypad with NumLock *off*: {KP1} is the key printed "1",
    # which Windows sends as End. {NUM1} is the same key with NumLock on.
    "KP0": VK_INSERT, "KP1": VK_END, "KP2": VK_DOWN, "KP3": VK_NEXT, "KP4": VK_LEFT,
    "KP5": VK_CLEAR, "KP6": VK_RIGHT, "KP7": VK_HOME, "KP8": VK_UP, "KP9": VK_PRIOR,
    "PGUP": VK_PRIOR, "PGDN": VK_NEXT,
}
# Named keys that Windows marks as extended: the dedicated navigation block
# (the keypad sends the same VKs without the flag).
EXTENDED_VKS = frozenset({VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN, VK_HOME, VK_END, VK_DELETE,
                          VK_PRIOR, VK_NEXT, VK_INSERT})
# Physical key for Ctrl combinations, written as {C-,} or {CS-/} (Ctrl+Shift).
CTRL_KEY_VK = {",": VK_OEM_COMMA, ".": VK_OEM_PERIOD, ";": VK_OEM_1, "'": VK_OEM_7, "/": VK_OEM_2,
               "-": VK_OEM_MINUS, "[": VK_OEM_4, "]": VK_OEM_6}
_TOKEN = re.compile(r"\{(CS|CA|C)-(.)\}|\{S-TAB\}()|\{([A-Z][A-Z0-9-]*)\}|(.)", re.S)


def parse(script: str) -> Iterator[str | int | KeyInput]:
    """Yield characters, VK codes for named keys ({SHIFT} -> VK_SHIFT), or a
    ready KeyInput for Ctrl combinations ({C-,}, {CS-/})."""
    for m in _TOKEN.finditer(script):
        mods, ctrl_key, shift_tab, name, ch = m.groups()
        if mods:
            vk = CTRL_KEY_VK.get(ctrl_key, ord(ctrl_key.upper()))
            yield KeyInput(vk=vk, ctrl=True, shift=mods == "CS", alt=mods == "CA")
        elif shift_tab is not None:
            yield KeyInput(vk=VK_TAB, shift=True)
        elif name and name.startswith("S-") and name[2:] in NAMED:
            yield KeyInput(vk=NAMED[name[2:]], shift=True, extended=NAMED[name[2:]] in EXTENDED_VKS)
        elif name:
            if name == "SHIFT":
                yield VK_SHIFT
            elif name in ("RALT", "RCTRL"):
                yield "{" + name + "}"
            elif name == "SPACE":
                yield " "
            elif name.startswith("KP") and name[2:].isdigit():
                # the keypad with NumLock off: a navigation VK, not extended
                yield KeyInput(vk=NAMED[name], extended=False)
            elif name.startswith("NUM") and name[3:].isdigit():
                d = int(name[3:])
                yield KeyInput(vk=VK_NUMPAD0 + d, char=str(d))
            else:
                yield NAMED[name]
        else:
            yield ch


def press(session: Session, item: str | int | KeyInput) -> tuple[bool, View]:
    """Send one key the way PIME would (filter, then handle). Returns (handled, view)."""
    if isinstance(item, KeyInput):
        handled = session.filter_key_down(item) and session.key_down(item)
        return handled, session.view()
    if item in ("{RALT}", "{RCTRL}"):
        vk = VK_MENU if item == "{RALT}" else VK_CONTROL
        down = KeyInput(vk=vk, alt=vk == VK_MENU, ctrl=vk == VK_CONTROL, extended=True)
        session.filter_key_down(down)
        up = KeyInput(vk=vk, extended=True)
        handled = session.filter_key_up(up) and session.key_up(up)
        if handled is False and session.cand is not None:
            handled = True  # (right Ctrl's key-up goes on to the app, but the panel opened)
        return handled, session.view()
    if item == VK_SHIFT:
        down = KeyInput(vk=VK_SHIFT, shift=True, scan=SCAN_RSHIFT)
        session.filter_key_down(down)
        up = KeyInput(vk=VK_SHIFT, scan=SCAN_RSHIFT)
        handled = session.filter_key_up(up) and session.key_up(up)
        return handled, session.view()
    if isinstance(item, str):
        key = KeyInput.from_char(item)
    else:
        # The dedicated navigation block is extended; the numeric keypad's
        # own ↓/End/PageDown (NumLock off) are not. Keep that difference,
        # or {DOWN} would read as "keypad 2" in the candidate window.
        key = KeyInput(vk=item, extended=item in EXTENDED_VKS)
    handled = session.filter_key_down(key) and session.key_down(key)
    return handled, session.view()


def run(session: Session, script: str) -> tuple[str, View]:
    """Type a script. Returns (all committed text + passthrough chars, final view).

    Keys the IME does not handle are "typed by the application", so they are
    appended to the output as well — this mirrors what the user would see.
    """
    out = []
    view = session.view()
    for item in parse(script):
        handled, view = press(session, item)
        out.append(view.commit)
        if not handled and isinstance(item, str):
            out.append(item)
    return "".join(out), view


def describe(view: View) -> str:
    parts = [f"comp={view.composition!r}", f"cur={view.cursor}"]
    if view.commit:
        parts.append(f"commit={view.commit!r}")
    if view.hint:
        parts.append(f"hint={view.hint}")
    if view.suggestion:
        parts.append("tab→" + " · ".join(view.suggestions or [view.suggestion]))
    if view.notice:
        parts.append(f"notice={view.notice}")
    if view.candidates is not None:
        notes = view.candidate_notes or [""] * len(view.candidates)
        cands = " ".join(f"{i + 1}.{c}" + (f"({n})" if n else "") for i, (c, n) in
                         enumerate(zip(view.candidates, notes)))
        parts.append(f"cand[{view.candidate_index}]: {cands}")
    parts.append(view.mode.value)
    return "  ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("--steps", action="store_true", help="print the state after every key")
    ap.add_argument("--real-memory", action="store_true",
                    help="use the real %%APPDATA%%\\SmartIME (default: a throwaway copy, "
                         "so reproducing a report never writes into your own dictionary)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with contextlib.ExitStack() as stack:
        if not args.real_memory:
            tmp = stack.enter_context(tempfile.TemporaryDirectory())
            os.environ["SMARTIME_USER_DIR"] = tmp
        _simulate(args)


def _simulate(args) -> None:
    from ..pime.server import build_engine

    session = Session(build_engine())
    committed = []
    view = session.view()
    for item in parse(args.script):
        handled, view = press(session, item)
        committed.append(view.commit)
        if args.steps:
            if isinstance(item, KeyInput):
                label = f"<ctrl{'+shift' if item.shift else ''} {item.vk:#x}>"
            else:
                label = item if isinstance(item, str) else f"<vk {item:#x}>"
            print(f"{label!r:>10} {'' if handled else '(pass) '}{describe(view)}")
    print("committed:", repr("".join(committed)))
    print("final    :", describe(view))


if __name__ == "__main__":
    main()
