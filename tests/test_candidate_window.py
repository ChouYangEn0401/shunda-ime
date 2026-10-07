"""Candidate window: groups in a deliberate order, the Tab filter, the
multi-column mode and the symbol grid (user feedback #6-2, #12)."""

import pytest

from smartime.devtools.simulate import run
from smartime.engine.panel import candidate_panel
from smartime.engine.session import Session


@pytest.fixture
def memory_session(tmp_path):
    from smartime import paths
    from smartime.config import Config
    from smartime.engine.decoder import Decoder
    from smartime.engine.layouts import DACHEN
    from smartime.engine.lexicon import Lexicon
    from smartime.engine.session import Engine, Session
    from smartime.engine.userdict import UserDict

    user = UserDict(tmp_path / "user.db")
    user.add("珍", "ㄓㄣ", "zh", "朋友")
    user.learn("偵", "ㄓㄣ", "zh")
    lex = Lexicon(paths.system_db_path(), user)
    s = Session(Engine(lexicon=lex, layout=DACHEN, decoder=Decoder(lex, DACHEN), config=Config()))
    yield s
    user.close()
    lex.close()


def test_my_words_then_learned_then_the_dictionary(memory_session):
    _, v = run(memory_session, "ji35p {DOWN}")
    groups = [c.group for c in memory_session.cand.items]
    first = {g: groups.index(g) for g in dict.fromkeys(groups)}
    assert list(first) == ["我的詞庫", "學過", "詞庫", "原始按鍵"]
    assert memory_session.cand.items[0].text == "珍" and memory_session.cand.items[0].annotation == "朋友"
    # the selection starts on what is on screen, so Enter keeps it
    assert memory_session.cand.current.text == v.composition[-1]


def test_tab_filters_one_group_at_a_time(memory_session):
    run(memory_session, "ji35p {DOWN}")
    cand = memory_session.cand
    run(memory_session, "{TAB}")
    assert cand.filter == "我的詞庫" and [c.text for c in cand.shown] == ["珍"]
    p = candidate_panel(memory_session)
    assert p.chip == "我的詞庫" and p.chips[0] == "全部"
    run(memory_session, "{TAB}{TAB}")
    assert cand.filter == "詞庫" and all(c.group == "詞庫" for c in cand.shown)
    run(memory_session, "{S-TAB}{S-TAB}{S-TAB}")
    assert cand.filter == ""  # back to 全部
    _, v = run(memory_session, "{TAB}1")
    assert v.composition == "我珍"


def test_single_column_turns_pages(session):
    run(session, "u4{DOWN}")
    cand = session.cand
    run(session, "{RIGHT}")
    assert cand.page == 1 and cand.columns == 1 and cand.first_page == 1


def test_multi_column_opens_and_folds_columns(session):
    session.cfg.candidate_multi_column = True
    run(session, "u4{DOWN}")
    cand = session.cand
    row = cand.index % cand.page_size
    run(session, "{RIGHT}{RIGHT}")
    assert cand.columns == 3 and cand.first_page == 0 and cand.page == 2
    assert cand.index % cand.page_size == row  # same row in the next column
    _, v = run(session, "{LEFT}{LEFT}")
    assert cand.page == 0 and cand.columns == 3
    run(session, "{LEFT}")  # nothing more on the left: fold back to one column
    assert cand.columns == 1
    # digits pick in the column the selection is in
    run(session, "{RIGHT}")
    page = cand.page_items()
    _, v = run(session, "2")
    assert v.composition.endswith(page[1].text)


def test_palette_is_a_grid(session):
    run(session, "ji3{RCTRL}{TAB}{TAB}")  # 希臘字母
    cand = session.cand
    assert cand.columns > 1  # several rows at once
    run(session, "{DOWN}{RIGHT}")
    assert cand.index == cand.page_size + 1
    p = candidate_panel(session)
    assert p.palette and p.chip == "希臘字母"
    expected = cand.page_items()[2].text
    _, v = run(session, "3")  # third symbol of the selection's row
    assert v.composition == "我" + expected


@pytest.mark.parametrize("n", [1, 3, 5, 7, 9])
def test_numeric_keypad_selects_with_numlock_either_way(session, n):
    """Reported: 「旁邊的 number 鍵就會壞掉」.

    With NumLock off the keypad sends Insert/End/↓/PageDown/Clear instead of
    digits; those fell through the candidate handler, which closed the window
    and typed into the document. Both spellings must pick the same candidate.
    """
    run(session, "ji35p {DOWN}")
    wanted = session.cand.page_items()[n - 1].text
    for keys in (f"{n}", f"{{NUM{n}}}", f"{{KP{n}}}"):
        s = Session(session.engine)
        run(s, "ji35p {DOWN}" + keys)
        assert s.view().composition == "我" + wanted, keys


def test_arrow_keys_still_move_the_selection(session):
    # the dedicated arrow block is "extended": it must not read as keypad 2/8
    _, v = run(session, "ji35p {DOWN}{DOWN}")
    assert v.candidates is not None and session.cand.index == 1
