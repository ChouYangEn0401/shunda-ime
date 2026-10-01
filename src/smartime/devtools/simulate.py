"""Type a key script into a Session without installing the IME.

Key script syntax: plain characters are typed as-is (``ji3`` = ㄨㄛˇ); named
keys go in braces: {BS} {DEL} {ENTER} {ESC} {TAB} {LEFT} {RIGHT} {UP} {DOWN}
{HOME} {END} {SHIFT} (a lone Shift tap), {SPACE}.

    uv run python -m smartime.devtools.simulate "ji3ap7{DOWN}"
    uv run python -m smartime.devtools.simulate --steps "su3cl3<"
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator

from ..engine.keys import (
    SCAN_RSHIFT, VK_BACK, VK_DELETE, VK_DOWN, VK_END, VK_ESCAPE, VK_HOME, VK_LEFT, VK_OEM_1,
    VK_OEM_2, VK_OEM_4, VK_OEM_6, VK_OEM_7, VK_OEM_COMMA, VK_OEM_MINUS, VK_OEM_PERIOD, VK_RETURN,
    VK_RIGHT, VK_SHIFT, VK_SPACE, VK_TAB, VK_UP, KeyInput,
)
from ..engine.session import Session, View

NAMED = {
    "BS": VK_BACK, "DEL": VK_DELETE, "ENTER": VK_RETURN, "ESC": VK_ESCAPE, "TAB": VK_TAB,
    "LEFT": VK_LEFT, "RIGHT": VK_RIGHT, "UP": VK_UP, "DOWN": VK_DOWN, "HOME": VK_HOME,
    "END": VK_END, "SPACE": VK_SPACE,
}
# Physical key for Ctrl combinations, written as {C-,} or {CS-/} (Ctrl+Shift).
CTRL_KEY_VK = {",": VK_OEM_COMMA, ".": VK_OEM_PERIOD, ";": VK_OEM_1, "'": VK_OEM_7, "/": VK_OEM_2,
               "-": VK_OEM_MINUS, "[": VK_OEM_4, "]": VK_OEM_6}
_TOKEN = re.compile(r"\{(CS?)-(.)\}|\{([A-Z]+)\}|(.)", re.S)


def parse(script: str) -> Iterator[str | int | KeyInput]:
    """Yield characters, VK codes for named keys ({SHIFT} -> VK_SHIFT), or a
    ready KeyInput for Ctrl combinations ({C-,}, {CS-/})."""
    for m in _TOKEN.finditer(script):
        mods, ctrl_key, name, ch = m.groups()
        if mods:
            vk = CTRL_KEY_VK.get(ctrl_key, ord(ctrl_key.upper()))
            yield KeyInput(vk=vk, ctrl=True, shift=mods == "CS")
        elif name:
            if name == "SHIFT":
                yield VK_SHIFT
            elif name == "SPACE":
                yield " "
            else:
                yield NAMED[name]
        else:
            yield ch


def press(session: Session, item: str | int | KeyInput) -> tuple[bool, View]:
    """Send one key the way PIME would (filter, then handle). Returns (handled, view)."""
    if isinstance(item, KeyInput):
        handled = session.filter_key_down(item) and session.key_down(item)
        return handled, session.view()
    if item == VK_SHIFT:
        down = KeyInput(vk=VK_SHIFT, shift=True, scan=SCAN_RSHIFT)
        session.filter_key_down(down)
        up = KeyInput(vk=VK_SHIFT, scan=SCAN_RSHIFT)
        handled = session.filter_key_up(up) and session.key_up(up)
        return handled, session.view()
    key = KeyInput.from_char(item) if isinstance(item, str) else KeyInput(vk=item)
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
        parts.append(f"tab→{view.suggestion}")
    if view.candidates is not None:
        cands = " ".join(f"{i + 1}.{c}" for i, c in enumerate(view.candidates))
        parts.append(f"cand[{view.candidate_index}]: {cands}")
    parts.append(view.mode.value)
    return "  ".join(parts)


def main() -> None:
    from ..pime.server import build_engine

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script")
    ap.add_argument("--steps", action="store_true", help="print the state after every key")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

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
