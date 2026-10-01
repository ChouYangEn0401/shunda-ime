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
