import pytest

from smartime.engine.decoder import Key, Kind


def decode(decoder, s, pins=()):
    return decoder.decode([Key(c) for c in s], pins)


@pytest.mark.parametrize(
    "keys, text",
    [
        ("ji3", "我"),
        ("ji3ap7", "我們"),
        ("e/4cl3", "更好"),
        ("su3cl3", "你好"),
        ("2026su06", "2026年"),
        ("hello world", "hello world"),
        ("ji3m/4python vu,3", "我用python 寫"),
        ("su3cl3<ji3ap7", "你好，我們"),
        ("ABC", "ABC"),
    ],
)
def test_exact_typing(decoder, keys, text):
    assert decode(decoder, keys).text == text


def test_stray_key_between_chinese_is_dropped(decoder):
    # 'e' left behind after deleting a failed syllable's tone (real log)
    d = decode(decoder, "ji3ee/4")
    assert d.text == "我更"
    assert any(s.kind is Kind.DROP for s in d.segments)


def test_zh_alternatives_for_english_token(decoder):
    alts = decoder.zh_alternatives([Key(c) for c in "i "], 0)
    assert "喔" in [s.text for s in alts]


def test_segments_carry_kinds(decoder):
    d = decode(decoder, "ji3m/4python vu,3")
    kinds = [s.kind for s in d.segments]
    assert Kind.EN in kinds and Kind.ZH in kinds and Kind.SPACE in kinds


def test_unfinished_syllable_is_pending_and_raw(decoder):
    d = decode(decoder, "ji3u.")
    assert d.text == "我u."
    assert d.segments[-1].kind is Kind.PENDING


def test_units_map_chars_to_key_spans(decoder):
    d = decode(decoder, "ji3ap7")
    assert [(a, b, ch) for a, b, ch, _ in d.units()] == [(0, 3, "我"), (3, 6, "們")]


def test_pin_forces_interpretation(decoder):
    first = decode(decoder, "ji3ap7")
    word = first.segments[0]
    # pin the second syllable to a different character
    from smartime.engine.decoder import Segment

    pin = Segment(3, 6, "門", Kind.ZH, -5.0, ("ㄇㄣ˙",), (3, 6), pinned=True)
    d = decode(decoder, "ji3ap7", [pin])
    assert d.text == "我門"
    assert word.text == "我們"


def test_every_input_decodes(decoder):
    # fallback edges guarantee a path for arbitrary garbage
    for s in ["`~!", "zzzz", "7777", "-=-=", ";;;", "ㄅ"]:
        assert decode(decoder, s).text


def test_decode_is_fast(decoder):
    import time

    keys = "ji3ap7vu;3rup4u4fu4m/4python vu,3x84" * 2
    decode(decoder, keys)  # warm caches
    t = time.perf_counter()
    decode(decoder, keys)
    assert (time.perf_counter() - t) < 0.05
