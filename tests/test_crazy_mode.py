"""瘋狂模式 (experimental, off by default): only the start of each syllable,
no tones — ㄨㄇ -> 我們 (user feedback #10)."""

import pytest

from smartime.config import Config
from smartime.devtools.simulate import run
from smartime.engine.panel import decode_panel


@pytest.fixture
def crazy(engine):
    from smartime.engine.session import Session

    engine.config = Config.from_dict({"crazy_mode": True})
    engine.decoder.apply_config(engine.config)
    yield Session(engine)
    engine.decoder.apply_config(Config.from_dict({"punct_style": "custom", "halfwidth_symbols": '"'}))


def test_off_by_default(session):
    _, v = run(session, "ja")
    assert v.composition == "ja"


def test_initials_become_words(crazy):
    _, v = run(crazy, "ja")
    assert v.composition == "我們"
    _, v = run(crazy, "rwu")  # ㄐ ㄊㄧ: 今天 (one or more symbols per syllable)
    assert v.composition == "我們今天"


def test_full_syllables_and_english_still_work(crazy):
    _, v = run(crazy, "su3cl3")
    assert v.composition == "你好"
    crazy._reset_buffer()
    _, v = run(crazy, "python")
    assert v.composition == "python"


def test_the_panel_shows_what_was_guessed(crazy):
    _, v = run(crazy, "jaji3")
    assert v.panel is not None  # always shown in this mode
    p = decode_panel(crazy)
    cols = [(c.keys, c.reading, c.text, c.abbreviated) for c in p.columns]
    assert cols[0][0] == "j" and cols[0][2] == "我" and cols[0][3]  # guessed
    assert cols[-1] == ("ji3", "ㄨㄛˇ", "我", False)  # typed in full
