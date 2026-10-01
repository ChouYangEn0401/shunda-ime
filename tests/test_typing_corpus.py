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
    ('ji3ap7"python"', '我們"python"'),  # Shift+' is a plain quote by default
    ("ji3o ", "我ㄟ"),  # reported: ㄟ became "o "
    ("o ", "ㄟ"),
    ("ij3", "我"),  # reported: ㄛㄨˇ
    ("/e4cl3", "更好"),  # reported: became "/好"
]


# Second test day: whole key scripts *including Backspace*, replayed through
# a Session. Fast typists fix a failed syllable by deleting only its last key
# (e4 ⌫ e/4), which leaves a lone letter behind ("我e更快", "在u想", "j往").
SESSION_REAL = [
    ("5k4u;4dk3s/6ji3e4{BS}e/4dj94", "這樣可能我更快"),
    ("ji3ur.4y94uv;'{BS}{BS}{BS}uv;3", "我就在想"),
    ("ji3dk31j4dk3u32; ji3rup uw0 j0{BS}j;3fu06", "我可不可以當我今天往前"),
    ("cl3dj4i ", "好酷喔"),  # i␣ = ㄛ = 喔, not the English word "i"
    ("2ji kx7cl32ji uvl3uvl3k27u/ jp6y4aj3", "多了好多小小的英文字母"),
    ("xo4n4vimu u;4fm4", "類似vim一樣去"),
    ("b06c.4ej0 m6 dictionary", "然後關於 dictionary"),
    ("183a.3uv, t;6m/4k27", "把某些常用的"),
    ("w.4eji4ru0320 k27z; g4ru8 bj4dictionaryxu3u0a4", "透過簡單的方式加入dictionary裡面"),
]


def decode(decoder, keys):
    return decoder.decode([Key(c) for c in keys]).text


@pytest.mark.parametrize("keys, expected", REAL)
def test_real_typing(decoder, keys, expected):
    assert decode(decoder, keys) == expected


@pytest.mark.parametrize("script, expected", SESSION_REAL)
def test_real_typing_with_edits(session, script, expected):
    from smartime.devtools.simulate import run

    _, view = run(session, script)
    assert view.composition == expected


@pytest.mark.parametrize("keys, expected", ENGLISH)
def test_english(decoder, keys, expected):
    assert decode(decoder, keys) == expected


@pytest.mark.parametrize("keys, expected", NUMBERS_AND_SYMBOLS)
def test_numbers_and_symbols(decoder, keys, expected):
    assert decode(decoder, keys) == expected
