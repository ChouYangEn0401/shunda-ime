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
    assert out == "你好，"  # Chinese punctuation comes from Ctrl
    s = styled()
    _, v = run(s, "ji3[ji3]")
    assert v.composition == "我[我]"


def test_fullwidth_style_is_the_older_behaviour(styled):
    s = styled(punct_style="fullwidth")
    out, _ = run(s, "su3cl3<")
    assert out == "你好，"


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
