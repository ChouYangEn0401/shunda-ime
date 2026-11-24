"""Punctuation keys in four layers (user feedback #8): alone / Shift type what
is printed on the keycap, Ctrl / Ctrl+Shift type Chinese punctuation, no two
combinations type the same thing, and every Ctrl cell can be changed."""

import pytest

from smartime.config import Config
from smartime.devtools.simulate import press, run
from smartime.engine import punct
from smartime.engine.keys import VK_OEM_COMMA, VK_OEM_PERIOD, KeyInput
from smartime.engine.layouts import DACHEN


@pytest.fixture
def styled(engine):
    """A session whose decoder follows the config (the real IME does)."""
    from smartime.engine.session import Session

    def make(**cfg):
        engine.config = Config.from_dict(cfg)
        engine.decoder.apply_config(engine.config)
        return Session(engine)

    yield make
    engine.decoder.apply_config(Config.from_dict({"punct_style": "custom", "halfwidth_symbols": '"'}))


def test_keycap_style_types_what_is_printed(styled):
    s = styled()  # the default style
    _, v = run(s, "su3cl3<")
    assert v.composition == "你好<"  # Shift+, is <, not ，
    _, v = run(s, "{DOWN}")
    assert "，" in v.candidates  # the full-width form is one ↓ away
    s = styled()
    out, v = run(s, "su3cl3{C-,}")
    # Chinese punctuation comes from Ctrl; the sentence is sent and the mark
    # stays in the composition so its width is still changeable
    assert out == "你好" and v.composition == "，"
    s = styled()
    _, v = run(s, "ji3[ji3]")
    assert v.composition == "我[我]"


def test_fullwidth_style_is_the_older_behaviour(styled):
    s = styled(punct_style="fullwidth")
    out, v = run(s, "su3cl3<")
    assert out + v.composition == "你好，"


def test_ctrl_cells_can_be_changed_or_given_back_to_the_app(styled):
    s = styled(punct_overrides={"C+,": "、", "C+.": ""})
    out, _ = run(s, "su3cl3{C-,}")
    assert out == "" and s.decoding.text == "你好、"
    handled, _ = press(s, KeyInput(vk=VK_OEM_PERIOD, ctrl=True))
    assert handled is False  # Ctrl+. goes to the app now


def test_the_four_layer_table():
    rows = {r["key"]: r for r in punct.table(Config(), DACHEN)}
    comma = rows[","]
    assert (comma["alone"], comma["aloneKind"]) == ("ㄝ", "zhuyin")
    assert (comma["shift"], comma["ctrl"], comma["ctrlShift"]) == ("<", "，", "《")
    assert rows["["]["alone"] == "[" and rows["["]["ctrl"] == "「"
    assert rows["1"]["shift"] == "!" and rows["1"]["ctrlShift"] == "！"
    # keycap style: nothing typed twice across the four layers of a key
    for r in rows.values():
        outs = [x for x in (r["alone"] if r["aloneKind"] == "symbol" else "", r["shift"], r["ctrl"], r["ctrlShift"]) if x]
        assert len(outs) == len(set(outs)), r
    old = {r["key"]: r for r in punct.table(Config(punct_style="fullwidth"), DACHEN)}
    assert old[","]["shift"] == "，"  # the duplicate the user pointed out


def test_unknown_override_keys_are_dropped():
    cfg = Config.from_dict({"punct_overrides": {"C+,": "、", "bogus": "x", "CS+/": "toolongvalue"}})
    assert cfg.punct_overrides == {"C+,": "、"}


@pytest.mark.parametrize("keys", ["ji3m06pnpm", "ji3m06venv", "ji3m06teh", "ji3m06wrold", "ji3m06python",
                                  "su3cl3ji3", "ji3 teh su3"])
@pytest.mark.parametrize("mark", ["{C-,}", "{C-.}", "{CS-/}"])
def test_a_mark_sends_exactly_what_was_on_screen(session, keys, mark):
    """「我現在看到文字以後，在我按下標點符號的那一剎那又出現變化」: pnpm went
    out as npm, teh as the, the last v of venv vanished. The mark closes the
    sentence; it must not re-read anything before it."""
    _, v = run(session, keys)
    shown = v.composition
    out, v = run(session, mark)
    assert (out + v.composition)[:-1] == shown


def test_ctrl_shift_on_the_digit_row_types_the_full_width_upper_symbol(session):
    """PunctInventory.md plan A: Ctrl+Shift is "the upper symbol, full-width"
    on every key; ＠＃＄％＆＊ had no key at all."""
    _, v = run(session, "ji3{CS-2}{CS-3}{CS-4}{CS-5}{CS-7}{CS-8}{CS-9}{CS-0}")
    assert v.composition == "我＠＃＄％＆＊（）"


def test_ctrl_minus_and_ctrl_slash_belong_to_the_app_when_nothing_is_typed(session):
    """Zoom out and toggle comment kept breaking: they are only — and … while
    composing (the user's choice)."""
    _, v = run(session, "{C--}{C-/}")
    assert v.composition == ""
    _, v = run(session, "ji3{C--}{C-/}")
    assert v.composition == "我—…"
    # 「」 and ， stay on Ctrl even with nothing typed
    s = type(session)(session.engine)
    _, v = run(s, "{C-[}")
    assert v.composition == "「"


@pytest.mark.parametrize("typed, wanted", [("@", "＠"), ("%", "％"), ("&", "＆"), ("*", "※"), ("=", "＝"),
                                           ("+", "±"), ("|", "｜")])
def test_down_after_any_symbol_offers_its_full_width_form(session, typed, wanted):
    """↓ after @ listed only @ itself."""
    run(session, "ji3" + typed + "{DOWN}")
    assert wanted in [c.text for c in session.cand.shown]


def test_the_taiwanese_interpunct_is_one_down_away(session):
    run(session, "ji3{C-/}{DOWN}")
    assert "‧" in [c.text for c in session.cand.shown]
