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
    assert b not in {r["id"] for r in u.quick_words()}  # nothing left to type


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
