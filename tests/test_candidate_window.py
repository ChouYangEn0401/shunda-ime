"""Candidate window: groups in a deliberate order, the Tab filter, the
multi-column mode and the symbol grid (user feedback #6-2, #12)."""

import pytest

from smartime.devtools.simulate import run
from smartime.engine.panel import candidate_panel
from smartime.engine.symbols import TABS
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


def test_arrows_walk_the_group_chips(session):
    """← → point at the row of chips above the list, so that is what they
    move along: the quick "show me only my own words" the report asked for.
    Paging moved to PageUp/PageDown — ↑↓ already roll into the next page."""
    run(session, "u4{DOWN}")
    cand = session.cand
    assert len(cand.groups()) > 1 and cand.filter == ""
    run(session, "{RIGHT}")
    assert cand.filter == cand.groups()[0]
    run(session, "{LEFT}")
    assert cand.filter == ""


def test_pageup_pagedown_turn_pages(session):
    run(session, "u4{DOWN}")
    cand = session.cand
    run(session, "{PGDN}")
    assert cand.page == 1 and cand.columns == 1 and cand.first_page == 1
    run(session, "{PGUP}")
    assert cand.page == 0


def test_grid_arrows_stay_on_their_own_axis(session):
    """Reported: 「左右操作變成上下、上下操作變成左右」.

    The symbol panel is a grid, one page per row. Moving by ±1 ran off the
    end of a row into the next one, so → behaved like "down"; ↑↓ moved by a
    whole page and were blocked at the edges, so they looked dead.
    """
    run(session, "ji3{RCTRL}{TAB}{TAB}")  # 希臘字母, a grid
    cand = session.cand
    n = cand.page_size
    assert cand.index == 0
    run(session, "{LEFT}")
    assert cand.index == 0, "← at the start of a row stays put"
    run(session, "{DOWN}")
    assert cand.index == n, "↓ goes straight down, same column"
    run(session, "{RIGHT}{RIGHT}")
    assert cand.index == n + 2
    run(session, "{UP}")
    assert cand.index == 2, "↑ comes back up the same column"
    for _ in range(n + 3):
        run(session, "{RIGHT}")
    assert cand.index == n - 1, "→ stops at the end of its row"


def test_palette_is_a_grid(session):
    run(session, "ji3{RCTRL}{TAB}{TAB}")  # 希臘字母
    cand = session.cand
    assert cand.columns > 1  # several rows at once
    p = candidate_panel(session)
    assert p.palette and p.layout == "grid" and p.chip == "希臘字母"
    assert p.title == "符號 · 希臘字母"
    expected = cand.page_items()[2].text
    _, v = run(session, "3")  # third symbol of the selection's row
    assert v.composition == "我" + expected


def test_tab_switches_the_symbol_category(session):
    run(session, "ji3{RCTRL}")
    assert session.cand.palette == 0
    run(session, "{TAB}")
    assert session.cand.palette == 1
    run(session, "{S-TAB}{S-TAB}")
    assert session.cand.palette == len(TABS) - 1  # wraps round to 顏文字


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
