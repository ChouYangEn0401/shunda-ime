"""快速詞: a trigger and the text it stands for (userdict side)."""

import pytest

from smartime.engine.userdict import UserDict


@pytest.fixture
def u(tmp_path):
    d = UserDict(tmp_path / "user.db")
    yield d
    d.close()


def test_quick_words_have_their_own_text_or_a_linked_snippet(u):
    a = u.add_quick_word("art", "artifact")
    sid = u.add_snippet("順打輸入法好棒 !!", "誇獎", "good")
    b = u.add_quick_word("順", snippet_id=sid)
    rows = {r["id"]: r for r in u.quick_words()}
    assert rows[a]["text"] == "artifact"
    assert rows[b]["text"] == "順打輸入法好棒 !!" and rows[b]["snippet_title"] == "誇獎"
    u.update_snippet(sid, body="順打真好用")
    assert {r["id"]: r["text"] for r in u.quick_words()}[b] == "順打真好用"  # follows the 片語
    u.delete_snippet(sid)
    rows = {r["id"]: r for r in u.quick_words()}
    assert rows[b]["text"] == "順打真好用" and rows[b]["snippet_id"] is None  # keeps the text, unlinked


def test_quick_word_checks(u):
    u.add_quick_word("art", "artifact")
    with pytest.raises(ValueError):
        u.add_quick_word("ART", "other")  # triggers are unique, any case
    with pytest.raises(ValueError):
        u.add_quick_word("a b", "x")
    with pytest.raises(ValueError):
        u.add_quick_word("x", "")
    with pytest.raises(ValueError):
        u.add_quick_word("x", snippet_id=999)
    qid = u.add_quick_word("ty", "thank you")
    u.update_quick_word(qid, "ty", "thank you very much")
    assert {r["trigger"]: r["text"] for r in u.quick_words()}["ty"] == "thank you very much"
    u.delete_quick_word(qid)
    assert [r["trigger"] for r in u.quick_words()] == ["art"]


# ------------------------------------------------------------- while typing
from smartime import paths  # noqa: E402
from smartime.config import Config  # noqa: E402
from smartime.devtools.simulate import run  # noqa: E402
from smartime.engine.decoder import Decoder  # noqa: E402
from smartime.engine.layouts import DACHEN  # noqa: E402
from smartime.engine.lexicon import Lexicon  # noqa: E402
from smartime.engine.session import Engine, Session  # noqa: E402


@pytest.fixture
def engine(u):
    u.add_quick_word("art", "artifact")
    u.add_quick_word("順", "順打輸入法好棒 !!")
    lex = Lexicon(paths.system_db_path(), u)
    yield Engine(lexicon=lex, layout=DACHEN, decoder=Decoder(lex, DACHEN), config=Config())
    lex.close()


def test_a_trigger_suggests_its_text_first_and_tab_types_it(engine):
    _, v = run(Session(engine), "art")
    assert v.suggestions[0] == "artifact" and v.suggestion_kinds[0] == "quick"
    out, v = run(Session(engine), "ji3art{TAB}")
    assert out == "我artifact" and v.composition == ""
    out, _ = run(Session(engine), "gjp4{TAB}")  # 順
    assert out == "順打輸入法好棒 !!"


def test_a_trigger_inside_a_word_is_not_one(engine):
    _, v = run(Session(engine), "start")
    assert "artifact" not in v.suggestions


def test_my_phrases_come_before_the_dictionarys(engine, u):
    _, v = run(Session(engine), "ji3ap7")  # 我們
    system = list(v.suggestions)
    assert set(v.suggestion_kinds) == {"system"}
    u.add("我們的專案", "ㄨㄛˇ-ㄇㄣ˙-ㄉㄜ˙-ㄓㄨㄢ-ㄢˋ", "zh", "")
    engine.lexicon.invalidate()
    _, v = run(Session(engine), "ji3ap7")
    assert v.suggestions[0] == "的專案" and v.suggestion_kinds[0] == "mine"
    assert v.suggestions[1:] == [s for s in system if s != "的專案"][:len(v.suggestions) - 1]
    panel = v.hint_panel
    assert panel.kinds[0] == "mine" and all(k == "system" for k in panel.kinds[1:])


# --------------------------------------------- shown beside a hint / typed out
@pytest.fixture
def opus(u):
    u.add_quick_word("o5m", "opus-5.5-medium")
    u.add_quick_word("sb", "順打輸入法好棒 !!")
    lex = Lexicon(paths.system_db_path(), u)
    yield Engine(lexicon=lex, layout=DACHEN, decoder=Decoder(lex, DACHEN), config=Config())
    lex.close()


def test_a_trigger_is_shown_even_when_a_key_of_it_is_dropped(opus):
    # o5m: the o is a stray to the decoder (略過 o ↓) and also my trigger —
    # both are right, so both are on screen (it used to work on Tab unseen)
    _, v = run(Session(opus), "o5m")
    assert "略過 o" in v.hint
    assert v.suggestions == ["opus-5.5-medium"] and v.suggestion_kinds == ["quick"]
    assert v.hint_panel.dropped == "o" and v.hint_panel.suggestion == "opus-5.5-medium"
    out, _ = run(Session(opus), "o5m{TAB}")
    assert out == "opus-5.5-medium"


def test_the_dictionarys_guesses_still_give_way_to_a_hint(opus):
    _, v = run(Session(opus), "ji3a")  # 我 + half a syllable: only the reading
    assert v.hint and v.suggestions == []


def test_typing_the_start_of_a_quick_words_text_offers_the_rest(opus):
    for typed, before in [("opu", ""), ("opus", ""), ("ji3opu", "我"), ("claude opu", "claude "),
                          ("opus-5.5-m", "")]:
        _, v = run(Session(opus), typed)
        assert v.suggestions[:1] == ["opus-5.5-medium"] and v.suggestion_kinds[0] == "quick", typed
        out, v = run(Session(opus), typed + "{TAB}")
        assert out == before + "opus-5.5-medium" and v.composition == "", typed


def test_the_start_of_a_text_needs_three_keys_a_word_start_and_not_all_of_it(opus):
    for typed in ["op", "gopus", "opus-5.5-medium"]:
        _, v = run(Session(opus), typed)
        assert "opus-5.5-medium" not in v.suggestions, typed
    out, _ = run(Session(opus), "opu ")  # never replaced without Tab
    assert "opus-5.5-medium" not in out


def test_a_chinese_text_is_offered_from_its_first_three_characters(opus):
    _, v = run(Session(opus), "gjp4283")  # 順打
    assert "順打輸入法好棒 !!" not in v.suggestions
    out, _ = run(Session(opus), "ji3gjp4283gj {TAB}")  # 我順打輸
    assert out == "我順打輸入法好棒 !!"
