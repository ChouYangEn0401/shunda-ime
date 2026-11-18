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
