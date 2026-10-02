"""超智慧推薦 (experimental, off by default): longer chains of what may come
next and homophones of the last word, picked with Shift+Tab (user feedback #6-1)."""

from smartime.devtools.simulate import run
from smartime.engine.panel import smart_panel


def test_off_by_default(session):
    run(session, "rup wu0 ")
    assert session.smart is None and smart_panel(session) is None


def test_homophone_fix_is_offered_and_picked(session):
    session.cfg.smart_suggest = True
    _, v = run(session, "2832.4cl4")
    assert v.composition == "打鬥號"
    assert [(f.annotation, f.text) for f in session.smart.fixes] == [("鬥號", "逗號")]
    p = smart_panel(session)
    assert p.fixes[0][1:] == ("鬥號", "逗號") and p.fixes[0][0]  # numbered for Shift+Tab
    _, v = run(session, "{S-TAB}")
    groups = [c.group for c in session.cand.items]
    assert "也許是" in groups
    n = p.fixes[0][0]
    _, v = run(session, n)
    assert v.composition == "打逗號"


def test_chains_extend_the_sentence(session):
    session.cfg.smart_suggest = True
    _, v = run(session, "rup wu0 ")
    assert v.composition == "今天"
    chains = [s.text for s in session.smart.chains]
    assert chains and all(c for c in chains)
    _, v = run(session, "{S-TAB}1")
    assert v.composition == "今天" + chains[0]


def test_stays_while_typing_the_next_syllable_and_goes_on_commit(session):
    session.cfg.smart_suggest = True
    run(session, "rup wu0 ")
    before = [s.text for s in session.smart.chains]
    _, v = run(session, "ji")  # an unfinished syllable: kept, not pickable
    assert session.smart.stale and [s.text for s in session.smart.chains] == before
    assert smart_panel(session).stale
    run(session, "{S-TAB}")
    assert session.cand is None or all(c.group != "長句" for c in session.cand.items)
    run(session, "{ESC}{ESC}{ENTER}")
    assert session.smart is None
