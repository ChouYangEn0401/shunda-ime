from smartime.engine import bopomofo
from smartime.engine.layouts import DACHEN


def test_compose_strict_accepts_canonical_order():
    assert bopomofo.compose_strict("ㄨㄛ", "ˇ") == "ㄨㄛˇ"
    assert bopomofo.compose_strict("ㄒㄩㄣ") == "ㄒㄩㄣ"


def test_compose_strict_rejects_wrong_order_and_duplicates():
    assert bopomofo.compose_strict("ㄛㄨ", "ˇ") is None
    assert bopomofo.compose_strict("ㄩㄒㄣ") is None
    assert bopomofo.compose_strict("ㄅㄆ") is None
    assert bopomofo.compose_strict("") is None


def test_tone_helpers():
    assert bopomofo.tone_of("ㄇㄣ˙") == "˙"
    assert bopomofo.tone_of("ㄉㄧㄥ") == ""
    assert bopomofo.strip_tone("ㄨㄛˇ") == "ㄨㄛ"


def test_dachen_covers_all_symbols_once():
    symbols = sorted(DACHEN.symbols.values())
    expected = sorted(bopomofo.INITIALS + bopomofo.MEDIALS + bopomofo.FINALS)
    assert symbols == expected
    assert sorted(DACHEN.tones.values()) == sorted(["", "ˊ", "ˇ", "ˋ", "˙"])


def test_dachen_reading_round_trip():
    assert DACHEN.keys_for_reading("ㄨㄛˇ-ㄇㄣ˙") == "ji3ap7"
    assert DACHEN.keys_for_reading("ㄍㄥˋ-ㄏㄠˇ") == "e/4cl3"
    assert DACHEN.keys_for_syllable("ㄉㄧㄥ") == "2u/ "
    assert DACHEN.symbols_for_keys("u.") == "ㄧㄡ"


def test_eten_layout(lexicon):
    from smartime.engine.decoder import Decoder, Key
    from smartime.engine.layouts import ETEN

    d = Decoder(lexicon, ETEN)
    # 我 ㄨㄛˇ = x o 3 ; 們 ㄇㄣ˙ = m 9 1 ; 你好 ㄋㄧˇ ㄏㄠˇ = n e 3 h z 3
    assert d.decode([Key(c) for c in "xo3m91"]).text == "我們"
    assert d.decode([Key(c) for c in "ne3hz3"]).text == "你好"
    assert ETEN.keys_for_reading("ㄨㄛˇ-ㄇㄣ˙") == "xo3m91"
    # the same keys in 大千 mean something else
    assert "'" in d.droppable and "=" in d.droppable


def test_layout_switch_through_config(lexicon):
    from smartime.config import Config
    from smartime.engine.decoder import Decoder, Key
    from smartime.engine.layouts import DACHEN

    d = Decoder(lexicon, DACHEN)
    cfg = Config()
    cfg.layout = "eten"
    d.apply_config(cfg)
    assert d.layout.name == "eten"
    assert d.decode([Key(c) for c in "xo3"]).text == "我"
