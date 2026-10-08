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


def test_arrows_open_and_fold_the_columns(session):
    """微軟新注音's shape, which the report asked for: the window starts as
    one tall list, → opens the next page beside it (the cursor keeps its
    row), ← walks back, and ← on the first column folds it up again."""
    run(session, "u4{DOWN}")
    cand = session.cand
    assert cand.columns == 1 and cand.pages > 2
    row = cand.index % cand.page_size

    run(session, "{RIGHT}")
    assert cand.columns == 2 and cand.page == 1
    assert cand.index % cand.page_size == row, "same row in the new column"
    run(session, "{RIGHT}")
    assert cand.columns == 3 and cand.page == 2

    run(session, "{LEFT}")
    assert cand.page == 1 and cand.columns == 3, "walking back keeps them open"
    run(session, "{LEFT}")
    assert cand.page == 0
    run(session, "{LEFT}")
    assert cand.columns == 1, "← on the first column folds the window back"


def test_tab_still_walks_the_groups(session):
    run(session, "u4{DOWN}")
    cand = session.cand
    assert len(cand.groups()) > 1 and cand.filter == ""
    run(session, "{TAB}")
    assert cand.filter == cand.groups()[0]
    run(session, "{S-TAB}")
    assert cand.filter == ""


def test_the_edge_either_grows_or_turns_the_page(session):
    from smartime.engine.session import MAX_COLUMNS

    run(session, "u4{DOWN}")
    cand = session.cand
    for _ in range(MAX_COLUMNS + 2):
        run(session, "{RIGHT}")
    assert cand.columns == MAX_COLUMNS and cand.first_page > 0, "grow, then scroll"


def test_left_slides_a_scrolled_window_back_before_collapsing_it(session):
    """Reported: once → had scrolled the window past MAX_COLUMNS (first_page
    > 0), pressing ← at the left edge closed the whole window immediately
    instead of sliding it back one column at a time — "column[i] should
    become column[i-1]", not a collapse-then-reopen-at-column-0."""
    from smartime.engine.session import MAX_COLUMNS

    run(session, "u4{DOWN}")
    cand = session.cand
    for _ in range(MAX_COLUMNS + 3):  # grow to MAX_COLUMNS, then scroll 3 more
        run(session, "{RIGHT}")
    scrolled_first_page = cand.first_page
    assert scrolled_first_page > 0 and cand.columns == MAX_COLUMNS

    # walk back onto the left edge of the currently-visible set — still the
    # same MAX_COLUMNS window, only the selection moves
    for _ in range(MAX_COLUMNS - 1):
        run(session, "{LEFT}")
    assert cand.first_page == scrolled_first_page and cand.columns == MAX_COLUMNS

    # one more ←, at the left edge: must slide, not collapse
    run(session, "{LEFT}")
    assert cand.first_page == scrolled_first_page - 1, "slid back one column"
    assert cand.columns == MAX_COLUMNS, "same width — not a collapse"

    # keep pressing ← exactly once per step until first_page truly reaches 0
    while cand.first_page > 0:
        before = cand.first_page
        run(session, "{LEFT}")
        assert cand.first_page == before - 1 and cand.columns == MAX_COLUMNS

    # only now, with nothing earlier left, does one more ← fold it up
    run(session, "{LEFT}")
    assert cand.columns == 1, "nothing earlier left: now it folds up"

    session.cfg.candidate_expand = "page"
    s2 = Session(session.engine)
    run(s2, "u4{DOWN}")
    run(s2, "{RIGHT}")
    # the whole set is swapped at once and the cursor starts on the left
    assert s2.cand.page == s2.cand.first_page == 1 and s2.cand.columns > 1
    for _ in range(MAX_COLUMNS - 1):
        run(s2, "{RIGHT}")
    assert s2.cand.page == s2.cand.first_page + MAX_COLUMNS - 1  # walked to the right edge
    run(s2, "{RIGHT}")
    assert s2.cand.page == s2.cand.first_page, "past the edge: another fresh set"


def test_pageup_pagedown_turn_pages(session):
    run(session, "u4{DOWN}")
    cand = session.cand
    run(session, "{PGDN}")
    assert cand.page == 1 and cand.columns == 1 and cand.first_page == 1
    run(session, "{PGUP}")
    assert cand.page == 0


def test_every_symbol_panel_tab_moves_the_same_way(session):
    """Reported: 「為什麼同樣是那一個框框裡面，操作的感覺彼此有差異」 — the
    symbol categories were a grid (1–9 across a row, ← → along it) while
    顏文字, 片語 and the rest were lists (1–9 down a column, ← → between
    columns). Every tab is a list now, the 顏文字 way the report singled out
    as the one that felt right."""
    def walk(tab):
        s = Session(session.engine)
        run(s, "ji3{RCTRL}")
        for _ in range(TABS.index(tab)):
            run(s, "{TAB}")
        cand, n, seen = s.cand, s.cand.page_size, []
        run(s, "{DOWN}")
        seen.append(cand.index)  # ↓ = the next one down the column
        run(s, "{RIGHT}")
        seen.append((cand.page, cand.index % n))  # → = the next column, same row
        run(s, "{LEFT}")
        seen.append((cand.page, cand.index % n))  # ← = back
        return seen

    assert walk("希臘字母") == walk("顏文字") == walk("emoji") == [1, (1, 1), (0, 1)]


def test_symbol_categories_are_grouped_lists(session):
    run(session, "ji3{RCTRL}{TAB}{TAB}")  # 希臘字母
    cand = session.cand
    assert cand.columns > 1  # several columns straight away
    assert [c.group for c in cand.shown[:1]] == ["小寫"] and cand.shown[-1].group == "大寫"
    p = candidate_panel(session)
    assert p.palette and p.chip == "希臘字母" and p.title == "符號 · 希臘字母"
    assert all(i.note == "" for i in p.items), "the tab name is in the title, not beside α"
    expected = cand.page_items()[2].text
    _, v = run(session, "3")  # third symbol of the selection's column
    assert v.composition == "我" + expected


def test_recently_used_symbols_get_their_own_group_in_common(session):
    run(session, "ji3{RCTRL}{TAB}{TAB}2")  # β, from 希臘字母
    run(session, "{RCTRL}")
    first = session.cand.shown[0]
    assert (first.text, first.group) == ("β", "最近")


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


def test_small_symbol_categories_spread_over_several_columns(session):
    """At nine rows a column 箭頭 came out as two columns, each stretched
    across the panel with one small glyph in it. Shorter columns keep every
    category wide and low, the shape the old grid had."""
    from smartime.engine.session import palette_rows

    for tab in TABS[:TABS.index("片語")]:
        s = Session(session.engine)
        run(s, "ji3{RCTRL}")
        for _ in range(TABS.index(tab)):
            run(s, "{TAB}")
        assert s.cand.columns >= 4, f"{tab}: {s.cand.columns} columns"
        assert 5 <= s.cand.page_size <= 9
    assert palette_rows(18, 9) == 5 and palette_rows(48, 9) == 8 and palette_rows(200, 9) == 9
    assert palette_rows(18, 3) == 3, "never more rows than the user's own page size"
