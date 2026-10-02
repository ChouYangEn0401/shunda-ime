"""Symbol panel (a lone right-Ctrl tap) and continuation suggestions (Tab, Shift+Tab)."""

from smartime.devtools.simulate import run
from smartime.engine.symbols import CATEGORIES, SymbolPanel


def test_palette_opens_with_categories_and_commits_directly(session):
    _, v = run(session, "{RCTRL}")
    assert v.candidates[:3] == ["，", "。", "、"]
    assert v.candidate_notes[0].startswith("常用")
    _, v = run(session, "{TAB}{TAB}")
    assert v.candidates[0] == "α" and v.candidate_notes[0].startswith("希臘字母")
    out, v = run(session, "2")
    assert out == "β" and v.candidates is None


def test_palette_inserts_into_the_composition(session):
    _, v = run(session, "ji3{RCTRL}{TAB}{TAB}1u.3")
    assert v.composition == "我α有"


def test_shift_tab_goes_back_and_hotkey_again_closes(session):
    _, v = run(session, "{RCTRL}{S-TAB}")
    assert v.candidate_notes[0].startswith(CATEGORIES[-1][0])
    _, v = run(session, "{RCTRL}")
    assert v.candidates is None


def test_palette_hotkey_setting(session):
    session.cfg.palette_hotkey = "off"
    _, v = run(session, "{RCTRL}")
    assert v.candidates is None
    session.cfg.palette_hotkey = "ralt"  # the older choice
    _, v = run(session, "{RCTRL}")
    assert v.candidates is None
    _, v = run(session, "{RALT}")
    assert v.candidates is not None


def test_right_ctrl_tap_vs_shortcut_vs_hold(session):
    from smartime.engine.keys import VK_CONTROL, KeyInput

    # Ctrl+C with the right Ctrl: a shortcut, no panel
    session.filter_key_down(KeyInput(vk=VK_CONTROL, ctrl=True, extended=True))
    session.filter_key_down(KeyInput(vk=ord("C"), ctrl=True))
    up = KeyInput(vk=VK_CONTROL, extended=True)
    assert not session.filter_key_up(up)
    # held long enough to be voice input: no panel
    import smartime.engine.session as sm

    session.filter_key_down(KeyInput(vk=VK_CONTROL, ctrl=True, extended=True))
    session._palette_down_at -= sm.CTRL_TAP_SECONDS + 0.05
    assert not session.filter_key_up(up)
    # a tap: the panel opens and the key-up still reaches the app
    session.filter_key_down(KeyInput(vk=VK_CONTROL, ctrl=True, extended=True))
    assert session.filter_key_up(up) and session.key_up(up) is False
    assert session.cand is not None and session.cand.palette == 0


def test_backtick_is_left_alone(session):
    # the user fences code with `
    _, v = run(session, "`")
    assert v.candidates is None


def test_recent_symbols_come_first(tmp_path):
    panel = SymbolPanel(tmp_path / "recent.json")
    panel.used("β")
    panel.used("→")
    again = SymbolPanel(tmp_path / "recent.json")
    name, symbols = again.category(0)
    assert name == "常用" and symbols[:2] == ["→", "β"]


def test_several_suggestions_and_shift_tab_list(session):
    _, v = run(session, "ao6u.3")
    assert v.composition == "沒有"
    assert len(v.suggestions) == 3 and v.suggestions[0] == v.suggestion
    _, v = run(session, "{S-TAB}")
    assert v.candidates[:3] == ["用", "的", "錢"]
    assert v.candidate_notes[0] == "沒有用"
    _, v = run(session, "3")
    assert v.composition == "沒有錢" and v.candidates is None


def test_suggestion_count_setting(session):
    session.cfg.suggestion_count = 1
    _, v = run(session, "ao6u.3")
    assert v.suggestions == [v.suggestion]


def test_only_a_lone_right_alt_tap_opens_the_palette(session):
    from smartime.engine.keys import VK_MENU, VK_TAB, KeyInput

    # left Alt tap: no
    session.filter_key_down(KeyInput(vk=VK_MENU, alt=True))
    up = KeyInput(vk=VK_MENU)
    assert not session.filter_key_up(up)
    # right Alt + Tab (Alt+Tab): no
    session.filter_key_down(KeyInput(vk=VK_MENU, alt=True, extended=True))
    session.filter_key_down(KeyInput(vk=VK_TAB, alt=True))
    assert not session.filter_key_up(KeyInput(vk=VK_MENU, extended=True))
    assert session.cand is None
