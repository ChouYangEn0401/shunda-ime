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


def test_turning_it_on_builds_the_index_before_the_first_key():
    """The index used to be built on the first key typed in 瘋狂模式, which
    stalled that key for about a third of a second (measured while chasing
    「打開以後速度感覺變超級慢」). Turning the mode on now starts it in the
    background."""
    import time

    from smartime import paths
    from smartime.config import Config
    from smartime.engine.decoder import Decoder
    from smartime.engine.layouts import DACHEN
    from smartime.engine.lexicon import Lexicon

    lex = Lexicon(paths.system_db_path())  # a fresh one: the shared fixture may already have it
    try:
        assert lex._abbr is None
        Decoder(lex, DACHEN).apply_config(Config.from_dict({"crazy_mode": True}))
        deadline = time.monotonic() + 15
        while lex._abbr is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert lex._abbr, "built in the background, without typing anything"
    finally:
        lex.close()
