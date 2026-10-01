"""Decoding accuracy on real typing.

The ``REAL`` cases are the user's actual keystrokes from the first test day
(2026-10-01, reconstructed from the PIME launcher log), paired with what they
meant to type. They include the typical fast-typing slips: syllable keys in
the wrong order (k27 for 的 = 2k7) and syllables made only of digit keys
(283 打, 204 但) that a naive decoder turns into numbers.

Every weight change in decoder.Weights must keep this file green.
"""

import pytest

from smartime.engine.decoder import Key

# The keys are decoded correctly but a unigram (word-frequency-only) model
# picks the more common homophone. Needs context: user learning (Phase 4)
# or a bigram language model. Remove the marker when they pass.
NEEDS_CONTEXT = pytest.mark.xfail(reason="homophone choice needs context LM / learning", strict=True)

REAL = [
    # keys as typed                       intended text
    pytest.param("2; ji3rup wu0 t;6g42832.4cl4", "當我今天嘗試打逗號", marks=NEEDS_CONTEXT),  # 打鬥號
    ("2; ji3rup wu0 t;6g4283", "當我今天嘗試打"),  # 283 must be 打, not a number
    ("yjo4284k27t8 u4", "最大的差異"),  # k27: ㄜㄉ˙ -> 的
    ("ru.4g41j4s/6283cp3dj94", "就是不能打很快"),  # 283 must be 打, not a number
    ("204fu6w8 cl3uv;4c96dk3u3", "但其他好像還可以"),  # 204 但; uv;4: ㄧㄒㄤˋ -> 像
    ("b06c.428454jp4wu6", "然後大致問題"),  # 284 54 大致
    ("su3u/ e9 u,3dk3u3d04tj x96kx7", "你應該也可以看出來了"),  # kx7 -> 了
    ("vu0 uv. 5k4u 1j4zp4", "先修這一部分"),  # uv. -> 修
    ("ru.4cjo4y94vscodexu3ua04", "就會在vscode裡面"),  # ua04 -> 面
    ("fu6ej94k27g4j;t ", "奇怪的視窗"),  # j;t -> 窗
    pytest.param("283tj x96k27y4b/6b06", "打出來的字仍然", marks=NEEDS_CONTEXT),  # 的自
    ("283tj x96k27", "打出來的"),
    pytest.param("j6z83fm41u04g4", "無法去辨識", marks=NEEDS_CONTEXT),  # 便是
    ("u/ jp6k27jp4wu6", "英文的問題"),
    ("cjo4rul4tj ", "會叫出"),
    ("cjo4j6z83g3m/4", "會無法使用"),
    ("xj048a3", "亂碼"),  # 8a3: ㄚㄇˇ -> 碼 (alone, 馬 is the right guess)
    ("xj04a83", "亂碼"),
    ("k27", "的"),
]

ENGLISH = [
    ("hello world", "hello world"),
    ("this is a test", "this is a test"),
    ("i love python", "i love python"),
    ("ji3m/4python vu,3", "我用python 寫"),
    ("ji3ap7rup wu0 mvp ", "我們今天mvp "),  # a known term stays English after Chinese
    ("mvp ", "mvp "),
]

NUMBERS_AND_SYMBOLS = [
    ("2026su06", "2026年"),
    ("3ek7", "3個"),
    pytest.param("100m06", "100元", marks=NEEDS_CONTEXT),  # 100員
    ("100", "100"),
    ("su3cl3<ji3ap7", "你好，我們"),
    ("ji3o ", "我ㄟ"),  # reported: ㄟ became "o "
    ("o ", "ㄟ"),
    ("ij3", "我"),  # reported: ㄛㄨˇ
    ("/e4cl3", "更好"),  # reported: became "/好"
]


def decode(decoder, keys):
    return decoder.decode([Key(c) for c in keys]).text


@pytest.mark.parametrize("keys, expected", REAL)
def test_real_typing(decoder, keys, expected):
    assert decode(decoder, keys) == expected


@pytest.mark.parametrize("keys, expected", ENGLISH)
def test_english(decoder, keys, expected):
    assert decode(decoder, keys) == expected


@pytest.mark.parametrize("keys, expected", NUMBERS_AND_SYMBOLS)
def test_numbers_and_symbols(decoder, keys, expected):
    assert decode(decoder, keys) == expected
