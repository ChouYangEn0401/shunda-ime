"""Golden tests: the parts the user signed off on, pinned down exactly.

The candidate window (選字) was called 「非常完美」 — and was then changed by
accident while the symbol panel next to it was being reworked (the help row,
drawn by the same function). Decoding quality slipped the same way: 嘗試 came
out 常示 and nothing failed. These tests record the approved behaviour and
fail on *any* change to it, so a change elsewhere cannot quietly alter it.

When a change to these is intended, regenerate and review the diff:

    set SMARTIME_UPDATE_GOLDEN=1 && .venv\\Scripts\\python -m pytest tests\\test_golden.py
"""

import json
import os
import re
from pathlib import Path

import pytest

from smartime.devtools.simulate import parse, press
from smartime.engine.panel import candidate_panel
from smartime.engine.session import Session

GOLDEN = Path(__file__).parent / "golden"
UPDATE = os.environ.get("SMARTIME_UPDATE_GOLDEN") == "1"

# Every way the 選字 window is opened and walked: columns, rolling over pages,
# paging, group filters, English and raw keys, dropped keys, correction mode,
# the Shift+Tab continuation list, the keypad.
CANDIDATE_SCENARIOS = {
    "zh-basic": "ji35p {DOWN}{DOWN}{DOWN}{UP}2",
    "zh-columns": "u4{DOWN}{RIGHT}{RIGHT}{LEFT}{LEFT}{LEFT}",
    "zh-roll": "u4{DOWN}" + "{DOWN}" * 12 + "{UP}{UP}",
    "zh-pages": "u4{DOWN}{PGDN}{PGDN}{PGUP}{LEFT}{RIGHT}",
    "zh-scroll": "u4{DOWN}" + "{RIGHT}" * 6 + "{LEFT}" * 7,
    "zh-filter": "ji35p {DOWN}{TAB}{TAB}{S-TAB}{RIGHT}{DOWN}",
    "zh-moved-back": "ji3a87{LEFT}{UP}{DOWN}{DOWN}2",
    "zh-moved-back-mid": "su3cl3ji3{LEFT}{LEFT}{DOWN}{DOWN}{RIGHT}",
    "en": "mvp {DOWN}{DOWN}{TAB}{DOWN}4",
    "raw": "o {DOWN}{DOWN}",
    "drop-end": "ji3ee{DOWN}{DOWN}",
    "drop-later": "ji3ee/4dj94{DOWN}{UP}",
    "fix-middle": "2832.4cl4{LEFT}{LEFT}{DOWN}{DOWN}{DOWN}4",
    "correction": "ji3a87{ESC}{DOWN}{DOWN}{ENTER}",
    "correction-left": "ji3ee/4dj94{ESC}{HOME}l{DOWN}{RIGHT}",
    "suggest-list": "ao6u.3{S-TAB}{DOWN}{RIGHT}{LEFT}",
    "keypad": "ji35p {DOWN}{KP3}",
    "esc-close": "ji35p {DOWN}{DOWN}{ESC}",
}


def check(name: str, actual) -> None:
    path = GOLDEN / f"{name}.json"
    if UPDATE or not path.exists():
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(actual, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if not UPDATE:
            pytest.fail(f"{path.name} did not exist; recorded it — review and commit it")
        return
    expected = json.loads(path.read_text(encoding="utf-8"))
    if actual != expected:
        lines = []
        for key in sorted(set(expected) | set(actual)):
            if expected.get(key) != actual.get(key):
                lines.append(f"{key}:\n  approved {expected.get(key)!r}\n  now      {actual.get(key)!r}")
        pytest.fail(f"{path.name} changed (set SMARTIME_UPDATE_GOLDEN=1 only if intended):\n" + "\n".join(lines[:12]))


def _window(session, measure) -> dict:
    c = session.cand
    out = {"comp": session.view().composition, "cursor": session.cursor}
    if c is None:
        return out
    p = candidate_panel(session)
    from smartime.ui.panels import _cand_help

    out.update(help=[f"{k} {v}" for k, v in _cand_help(p)], index=c.index, page=c.page, first=c.first_page, cols=c.columns, rows=c.page_size,
               filter=c.filter, groups=c.groups(), chips=p.chips, chip=p.chip, title=p.title,
               column=[f"{i.label}|{i.text}|{i.group}|{i.note}" for i in p.items[c.page * c.page_size:
                                                                          (c.page + 1) * c.page_size]],
               size=measure(p))
    return out


@pytest.fixture(scope="module")
def measure():
    """The window's size as drawn (help row included), at 100 % scale."""
    from smartime.ui.canvas import Canvas, Fonts, Surface
    from smartime.ui.panels import paint_candidates
    from smartime.ui.theme import LIGHT

    fonts, surf = Fonts(1.0), Surface(4, 4)
    canvas = Canvas(surf.hdc, 1.0, fonts)

    def size(panel):
        painted = paint_candidates(canvas, LIGHT, panel, draw=False)
        return [round(painted.width), round(painted.height)]

    yield size
    canvas.close()
    surf.close()
    fonts.close()


def test_the_candidate_window_is_exactly_as_approved(engine, measure):
    record = {}
    for name, script in CANDIDATE_SCENARIOS.items():
        s = Session(engine)
        steps = []
        for key in parse(script):
            press(s, key)
            steps.append(_window(s, measure))
        record[name] = steps
    check("candidate_window", record)


# ---------------------------------------------------------------- decoding
def _phrases() -> list[str]:
    root = Path(__file__).resolve().parents[1]
    text = "".join((root / p).read_text(encoding="utf-8")
                   for p in ("README.md", "docs/install.md", "docs/keys.md", "docs/architecture.md"))
    seen: list[str] = []
    for run_ in re.findall(r"[一-鿿]{4,10}", text):
        if run_ not in seen:
            seen.append(run_)
    return seen[:400]


def test_decoding_of_real_sentences_does_not_get_worse(engine):
    """Real Chinese from the project's own documents, typed key for key with
    an empty dictionary. Recorded once; a decoder or scoring change that
    turns any of them into something else fails here instead of in the
    user's hands (嘗試 -> 常示 is the kind of thing this is for)."""
    from smartime.devtools.keyscript import script_for

    engine.config.autocomplete = False
    record = {}
    for phrase in _phrases():
        keys = script_for(phrase, engine.lexicon, engine.layout)
        if keys:
            record[phrase] = press_all(engine, keys)
    check("decoding", record)


def press_all(engine, keys: str) -> str:
    s = Session(engine)
    view = None
    for key in parse(keys):
        _, view = press(s, key)
    return view.composition if view else ""
