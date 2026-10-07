"""The decode panel (按鍵／注音／國字 columns) and its offscreen rendering."""

import os

import pytest

from smartime.devtools.simulate import run
from smartime.engine.panel import decode_panel


def cols(panel):
    return [(c.keys, c.reading, c.text, c.role) for c in panel.columns]


def test_columns_show_keys_reading_and_text(session):
    run(session, "ji3ee/4dj94python")
    p = decode_panel(session)
    assert cols(p) == [
        ("ji3", "ㄨㄛˇ", "我", "zh"),
        ("e", "略過", "", "drop"),  # the stray key is visible here
        ("e/4", "ㄍㄥˋ", "更", "zh"),
        ("dj94", "ㄎㄨㄞˋ", "快", "zh"),
        ("python", "英文", "python", "en"),
    ]
    assert p.mode == "typing" and p.caret == len(p.columns)


def test_columns_of_one_word_share_it(session):
    run(session, "ji3ap7")
    p = decode_panel(session)
    assert [c.text for c in p.columns] == ["我", "們"] and p.columns[0].word == p.columns[1].word


def test_keys_typed_out_of_order_are_marked(session):
    run(session, "k27ji3")
    p = decode_panel(session)
    assert p.columns[0].reading == "ㄉㄜ˙" and p.columns[0].reordered
    assert not p.columns[1].reordered


def test_unfinished_syllable_is_one_column(session):
    run(session, "ji3u.")
    p = decode_panel(session)
    assert cols(p)[-1] == ("u.", "ㄧㄡ", "…", "pending")


def test_correction_focus_follows_the_cursor(session):
    run(session, "ji3ee/4dj94{ESC}h")
    p = decode_panel(session)
    assert p.mode == "correcting" and p.columns[p.focus].text == "更"
    run(session, "vv{HOME}lll")  # 按鍵 view: the stray e
    p = decode_panel(session)
    assert p.layer == "keys" and p.columns[p.focus].role == "drop" and p.focus_key == 0


def test_chosen_and_learned_characters_are_marked(session):
    run(session, "ji3a87{LEFT}{UP}2")
    p = decode_panel(session)
    assert p.columns[1].text == "嘛" and p.columns[1].chosen and not p.columns[0].chosen


def test_the_view_carries_the_panel_when_wanted(session):
    _, v = run(session, "ji3")
    assert v.panel is None  # default: only in correction mode
    _, v = run(session, "{ESC}")
    assert v.panel is not None and v.panel.mode == "correcting"
    session.cfg.panel_decode = "always"
    _, v = run(session, "i")
    assert v.panel is not None and v.panel.mode == "typing"
    session.cfg.panel_decode = "off"
    _, v = run(session, "{ESC}")
    assert v.panel is None


@pytest.mark.skipif(os.name != "nt", reason="GDI rendering")
@pytest.mark.parametrize("script", ["ji3ee/4dj94k27python", "ji3u.", "ji3ee/4{ESC}", "ji3ee/4{ESC}vv{HOME}lll",
                                    "b06c.4283tj x96k27y4b/6b06j6z83fm4u/ jp6k27jp4{ESC}hhh"])
def test_panels_render_offscreen(session, script):
    from smartime.ui.canvas import Canvas, Fonts, Surface
    from smartime.ui.panels import MAX_WIDTH, paint_decode
    from smartime.ui.theme import DARK, LIGHT

    run(session, script)
    panel = decode_panel(session)
    for theme in (LIGHT, DARK):
        fonts = Fonts(1.25)
        surf = Surface(4, 4)
        size = paint_decode(Canvas(surf.hdc, 1.25, fonts), theme, panel, draw=False)
        surf.close()
        assert 100 < size.width <= MAX_WIDTH + 40 and 60 < size.height < 200
        surf = Surface(round(size.width * 1.25), round(size.height * 1.25))
        canvas = Canvas(surf.hdc, 1.25, fonts)
        painted = paint_decode(canvas, theme, panel)
        lo, hi = painted.regions["visible"]
        focus = panel.focus if panel.focus is not None else max(0, panel.caret - 1)
        assert lo <= focus < hi  # the cursor is always in view
        pixels = surf.rgb_bytes()
        assert len(set(pixels[i:i + 3] for i in range(0, len(pixels), 3 * 97))) > 3  # something was drawn
        canvas.close()
        surf.close()
        fonts.close()


def test_the_strip_stays_as_a_dot_while_composing(session):
    """Reported: in editors that draw no underline under composing text
    (Sublime Text) a click elsewhere dropped a whole sentence with no
    warning. Something has to stay on screen for as long as text is not
    committed yet."""
    from smartime.ui.theme import LIGHT

    from smartime.engine.panel import HintPanel

    v = run_view(session, "ji3ap7")
    assert v.hint_panel is not None and v.hint_panel.composing

    size = measure_hint(HintPanel(composing=True), LIGHT)
    assert size.width < 30 and size.height < 30, "with nothing to say it is only a dot"
    bigger = measure_hint(HintPanel(composing=True, reading="ㄊㄧㄢ"), LIGHT)
    assert bigger.width > size.width  # and it grows into the strip when there is

    v = run_view(session, "{ENTER}")
    assert v.hint_panel is None  # committed: nothing left on screen


def run_view(session, script):
    from smartime.devtools.simulate import run

    _, v = run(session, script)
    return v


def measure_hint(panel, theme):
    from smartime.ui.canvas import Canvas, Fonts, Surface
    from smartime.ui.panels import paint_hint

    fonts = Fonts(1.0)
    surf = Surface(4, 4)
    try:
        return paint_hint(Canvas(surf.hdc, 1.0, fonts), theme, panel, draw=False)
    finally:
        surf.close()
        fonts.close()
