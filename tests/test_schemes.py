"""拼音 and 倉頡五代: decoding, mixing with English, and the session pieces
(modes, hints, candidates, Tab continuations) that depend on the scheme."""

import pytest

from smartime.config import Config
from smartime.devtools.simulate import run
from smartime.engine.decoder import Key
from smartime.engine.pinyin import PinyinTable, to_pinyin
from smartime.engine.session import Mode


@pytest.fixture(autouse=True)
def needs_schema_2(lexicon):
    if not (lexicon.has_pinyin and lexicon.has_cangjie):
        pytest.skip("system lexicon predates pinyin/Cangjie; rebuild with tools/build_data.py")


def decode(decoder, keys, scheme, english=False):
    return decoder.decode([Key(c) for c in keys], allow_english=english, scheme=scheme).text


# ---------------------------------------------------------------- pinyin
@pytest.mark.parametrize("plain, spelled", [
    ("ㄨㄛ", "wo"), ("ㄓㄨㄤ", "zhuang"), ("ㄌㄩ", "lv"), ("ㄐㄩ", "ju"), ("ㄒㄩㄝ", "xue"), ("ㄩㄣ", "yun"),
    ("ㄐㄩㄥ", "jiong"), ("ㄉㄨㄥ", "dong"), ("ㄨㄥ", "weng"), ("ㄓ", "zhi"), ("ㄙ", "si"), ("ㄅㄛ", "bo"),
    ("ㄌㄧㄡ", "liu"), ("ㄉㄨㄟ", "dui"), ("ㄌㄨㄣ", "lun"), ("ㄧ", "yi"), ("ㄦ", "er"),
])
def test_pinyin_spelling(plain, spelled):
    assert to_pinyin(plain) == spelled


def test_pinyin_table_accepts_lue_nue():
    table = PinyinTable(["ㄌㄩㄝ", "ㄋㄩㄝ", "ㄌㄨㄛ"])
    assert table.lookup("lue") == ("ㄌㄩㄝ",) and table.lookup("lve") == ("ㄌㄩㄝ",)
    assert table.lookup("luo") == ("ㄌㄨㄛ",)


@pytest.mark.parametrize("keys, expected", [
    ("women", "我們"),
    ("jintiantianqihenhao", "今天天氣很好"),
    ("lvse", "綠色"),
    ("shurufa ", "輸入法"),  # a space ends the word and is not typed
    ("ma3", "馬"),  # an optional tone digit
    ("ma2", "麻"),  # 嗎 also has a first-tone reading in the data, so ma1 is ambiguous
])
def test_pinyin_decoding(decoder, keys, expected):
    assert decode(decoder, keys, "pinyin") == expected


def test_pinyin_mixes_with_english_in_auto_mode(decoder):
    assert decode(decoder, "women de deadline shi mingtian", "pinyin", english=True) == "我們的 deadline 是明天"
    assert decode(decoder, "i am a good guy", "pinyin", english=True) == "i am a good guy"


def test_unfinished_pinyin_waits(decoder):
    assert decode(decoder, "wom", "pinyin") == "我m"


# ---------------------------------------------------------------- Cangjie
@pytest.mark.parametrize("keys, expected", [
    ("hqi ", "我"),
    ("hqi oan ", "我們"),  # a word: the dictionary picks the characters
    ("onf vnd ", "你好"),
    ("ir evfn ", "台灣"),
])
def test_cangjie_decoding(decoder, keys, expected):
    assert decode(decoder, keys, "cangjie") == expected


def test_cangjie_code_waits_for_space_with_radical_hint(session):
    session.set_mode(Mode.CANGJIE)
    _, v = run(session, "hqi")
    assert v.composition == "hqi"
    assert v.hint.startswith("竹手戈") and "我" in v.hint
    _, v = run(session, " ")
    assert v.composition == "我"


def test_cangjie_candidates_are_the_characters_of_the_code(session):
    session.set_mode(Mode.CANGJIE)
    _, v = run(session, "hqi {DOWN}")
    assert v.candidates[0] == "我" and len(v.candidates) > 1


def test_unit_keys_per_scheme(decoder):
    assert decoder.unit_keys("pinyin", "們", "ㄇㄣ˙") == "men"
    assert decoder.unit_keys("cangjie", "們", "ㄇㄣ˙") == "oan "
    assert decoder.unit_keys("zhuyin", "們", "ㄇㄣ˙") == "ap7"


def test_tab_continuation_types_in_the_current_scheme(session):
    session.set_mode(Mode.PINYIN)
    _, v = run(session, "zhongguo")
    if v.suggestion is None:
        pytest.skip("no continuation for 中國 in this lexicon")
    expected = v.composition + v.suggestion
    _, v = run(session, "{TAB}")
    assert v.composition == expected
    typed = "".join(k.char for k in session.keys)
    assert typed.startswith("zhongguo") and typed.isascii()  # pinyin, not zhuyin keys


# ---------------------------------------------------------------- modes
def test_auto_mode_uses_the_chosen_chinese_scheme(session):
    session.cfg.chinese_scheme = "pinyin"
    _, v = run(session, "women meeting")
    assert v.composition == "我們 meeting"
    assert session.mode_label() == "中英自動（拼音）"


def test_shift_cycles_through_the_modes_turned_on(session):
    session.cfg.mode_cycle = "auto,english,pinyin,cangjie"
    seen = []
    for _ in range(4):
        _, v = run(session, "{SHIFT}")
        seen.append(v.mode)
    assert seen == [Mode.ENGLISH, Mode.PINYIN, Mode.CANGJIE, Mode.AUTO]


def test_config_keeps_known_modes_in_order():
    cfg = Config.from_dict({"mode_cycle": "cangjie, klingon,auto", "chinese_scheme": "wubi"})
    assert cfg.mode_cycle == "auto,cangjie"
    assert cfg.chinese_scheme == "zhuyin"


def test_pinyin_candidates_start_with_the_character_itself(session):
    # "tian" can also split as ti+an (堤岸); the character's own
    # alternatives come first
    session.set_mode(Mode.PINYIN)
    _, v = run(session, "jintian{LEFT}{DOWN}")
    assert len(v.candidates[0]) == 1 and "天" in v.candidates[:3]
