"""The emoji tab (the searchable symbol catalogue, first called 搜尋符號) and 我的符號 (the user's own
pasted symbols/kaomoji): the ``:::`` entry point, keyword filtering, and the
palette bugs found while building them.
"""

import pytest

from smartime.config import Config
from smartime.devtools.simulate import run
from smartime.engine.panel import candidate_panel
from smartime.engine.session import Engine, Session
from smartime.engine.symbols import EMOJI_SYMBOLS, EMOJI_TAB, TABS


def goto(session, tab: str) -> None:
    """Open the palette and Tab-cycle to ``tab``, the way a real user would
    who never memorised a shortcut for it."""
    run(session, "{RCTRL}")
    for _ in range(TABS.index(tab)):
        run(session, "{TAB}")


@pytest.fixture
def user_engine(tmp_path):
    """An Engine whose lexicon has a real UserDict behind it — the plain
    `engine`/`session` fixtures have none (lexicon.user is None), so custom
    symbols have nowhere to be stored."""
    from smartime import paths
    from smartime.engine.decoder import Decoder
    from smartime.engine.layouts import DACHEN
    from smartime.engine.lexicon import Lexicon
    from smartime.engine.userdict import UserDict

    user = UserDict(tmp_path / "user.db")
    lex = Lexicon(paths.system_db_path(), user)
    eng = Engine(lexicon=lex, layout=DACHEN, decoder=Decoder(lex, DACHEN), config=Config())
    eng.decoder.apply_config(eng.config)
    yield eng
    lex.close()
    user.close()


@pytest.fixture(autouse=True)
def keycap_colons(engine):
    """The shared `session`/`engine` fixtures build a Decoder with its bare
    constructor default (halfwidth_symbols='"' only), not the shipped
    "keycap" style apply_config() would set — so ':' alone decodes as the
    full-width '：' there, unlike in the real, configured product. Applying
    the real default here is what makes composition text in these tests
    read as literal ':' the way an actual user sees it; it does not change
    what the trigger-detection logic compares against (that always reads
    the raw typed Key.char, never the rendered punctuation)."""
    engine.config = Config()
    engine.decoder.apply_config(engine.config)
    yield
    engine.decoder.apply_config(Config.from_dict({"punct_style": "custom", "halfwidth_symbols": '"'}))


# ---------------------------------------------------------------- the catalogue itself
def test_the_catalogue_is_a_real_curated_set_within_the_bmp():
    """Every candidate here is drawn through plain GDI (no colour-font
    support in this renderer), so nothing outside the Unicode BMP belongs
    in it — that would show as a tofu box, not an emoji."""
    assert len(EMOJI_SYMBOLS) > 50
    for sym, cat, tags in EMOJI_SYMBOLS:
        assert len(sym) == 1 and ord(sym) <= 0xFFFF, sym
        assert cat and tags


# ---------------------------------------------------------------- opening it
def test_colon_colon_colon_opens_search_from_a_cold_start(session):
    """The user's own ask: "可以用 ':::' 開啟". The first two colons open
    the ordinary panel via the existing trigger; the third pivots into
    search instead of becoming a literal colon or re-opening the plain
    panel again."""
    _, v = run(session, "ji3:::")
    assert v.candidates is not None
    assert TABS[session.cand.palette] == EMOJI_TAB
    assert v.composition == "我::"  # exactly the two real colons, no third


def test_colon_colon_colon_at_the_very_start_of_the_buffer(session):
    out, v = run(session, ":::")
    assert v.candidates is not None
    assert TABS[session.cand.palette] == EMOJI_TAB
    assert v.composition == "::" and out == ""


def test_a_further_colon_pivots_from_any_tab_into_search(session):
    """Not just the first time: ':' from any symbol-family tab jumps to
    search, so "打開面板、按個冒號" works regardless of which tab you
    happen to be browsing."""
    run(session, "ji3{RCTRL}{TAB}{TAB}")  # 希臘字母, a grid tab
    _, v = run(session, ":")
    assert TABS[session.cand.palette] == EMOJI_TAB

    run(session, "{ESC}{ESC}")
    goto(session, "顏文字")
    _, v = run(session, ":")
    assert TABS[session.cand.palette] == EMOJI_TAB


def test_colon_inside_the_search_tab_itself_does_not_re_pivot(session):
    run(session, "ji3:::")
    run(session, ":")  # would only matter if this re-opened/reset the tab
    assert session.cand is not None and TABS[session.cand.palette] == EMOJI_TAB
    assert session.cand.query == ":"  # it became part of the search text instead


# ---------------------------------------------------------------- search filtering
def test_typed_keywords_filter_by_tag_or_category(session):
    run(session, "ji3:::")
    out, v = run(session, "heart")
    texts = [c.text for c in session.cand.shown]
    wanted = {sym for sym, cat, tags in EMOJI_SYMBOLS if "heart" in cat.lower() or "heart" in tags}
    assert texts and set(texts) == wanted


def test_typed_keywords_match_the_zh_category_label_too(session):
    run(session, "ji3:::")
    out, v = run(session, "星座")
    texts = [c.text for c in session.cand.shown]
    assert texts == [sym for sym, cat, _ in EMOJI_SYMBOLS if cat == "星座"]


def test_items_carry_no_per_item_label_only_a_category_group(session):
    """Reported: "emoji 旁邊不用放文字…用類似『顏文字』哪裡把東西分類好就好"
    — grouped by category with a section header, like 顏文字's mood groups,
    not a text annotation next to every single symbol."""
    run(session, "ji3:::")
    assert all(c.annotation == "" for c in session.cand.shown)
    assert {c.group for c in session.cand.shown} >= {"星星", "愛心", "勾叉"}


def test_a_symbol_in_two_categories_appears_once_per_category(session):
    """♥ is deliberately tagged under both 愛心 and 花色 — the real heart
    suit is also a heart. Grouping must not silently drop the duplicate."""
    run(session, "ji3:::")
    hearts = [c for c in session.cand.shown if c.text == "♥"]
    assert {c.group for c in hearts} == {"愛心", "花色"}


def test_recently_used_get_their_own_group_up_front(session):
    run(session, "ji3:::")
    picked = session.cand.shown[0].symbol
    run(session, "{ENTER}")
    run(session, "ji3:::")
    first = session.cand.shown[0]
    assert first.symbol == picked and first.group == "最近"


def test_extra_catalogue_merges_in_only_when_downloaded_and_enabled(session, tmp_path, monkeypatch):
    """The optional, user-downloaded pack (symbols_extra.py, tools/
    build_symbols_extra.py) is additive: it must change nothing for anyone
    who hasn't both turned it on *and* downloaded it, the same shape as
    voice_enabled needing a model before it does anything."""
    import json

    from smartime.engine import symbols_extra
    from smartime.engine.session import Session

    monkeypatch.setattr(symbols_extra, "path", lambda: tmp_path / "symbols-extra.json")

    session.cfg.symbols_extra_enabled = True
    s1 = Session(session.engine)
    run(s1, "ji3:::direct")
    assert "沒有符合" in s1.cand.current.text  # enabled, but nothing downloaded: no crash, no result

    symbols_extra.path().write_text(
        json.dumps([["⎓", "技術符號", ["direct", "current"]]]), encoding="utf-8")

    s2 = Session(session.engine)
    run(s2, "ji3:::direct")
    assert [c.text for c in s2.cand.shown] == ["⎓"]

    session.cfg.symbols_extra_enabled = False  # downloaded, but turned off: filtered back out
    s3 = Session(session.engine)
    run(s3, "ji3:::direct")
    assert "沒有符合" in s3.cand.current.text


def test_no_match_shows_a_placeholder_and_does_not_crash_on_pick(session):
    run(session, "ji3:::")
    run(session, "nosuchsymbolxyz")
    _, v = run(session, "{ENTER}")
    assert v.candidates is not None  # placeholder row, picking it is a no-op
    assert "沒有符合" in session.cand.current.text


def test_backspace_edits_the_query_without_crashing(session):
    run(session, "ji3:::")
    run(session, "star")
    _, v = run(session, "{BS}{BS}")
    assert session.cand.query == "st"


def test_picking_a_result_cleans_up_the_whole_trigger_and_query(session):
    """Reported indirectly while building this: picking after filtering must
    remove the "::" that opened the panel *and* every filter letter typed
    since — not just one or the other."""
    run(session, "ji3:::star")
    wanted = session.cand.shown[0].symbol
    out, v = run(session, "{ENTER}")
    assert (out + v.composition) == ("我" + wanted)


def test_escape_closes_the_cold_start_search_keeping_the_literal_colons(session):
    out, v = run(session, "ji3:::star{ESC}")
    assert v.candidates is None
    assert v.composition == "我::star"  # nothing silently deleted


# ---------------------------------------------------------------- 我的符號
def test_my_symbols_tab_shows_pasted_content(user_engine):
    engine = user_engine
    engine.lexicon.user.add_custom_symbols("★\n(=^・ω・^=)")
    s = Session(engine)
    goto(s, "我的符號")
    assert [c.text for c in s.cand.shown] == ["★", "(=^・ω・^=)"]
    p = candidate_panel(s)
    assert p.chip == "我的符號"


def test_my_symbols_empty_state_explains_where_to_add_them(user_engine):
    s = Session(user_engine)
    goto(s, "我的符號")
    assert "設定頁" in s.cand.current.text


def test_picking_a_multichar_custom_symbol_commits_it_whole(user_engine):
    engine = user_engine
    engine.lexicon.user.add_custom_symbols("(=^・ω・^=)")
    s = Session(engine)
    run(s, "ji3")
    goto(s, "我的符號")
    out, v = run(s, "1")
    assert out + v.composition == "我(=^・ω・^=)"


def test_picking_a_single_char_custom_symbol_stays_editable(user_engine):
    """Single-character entries go through the inline-pin path (like the
    built-in grid symbols), not a full commit — so typing continues right
    after it, unlike a multi-character kaomoji."""
    engine = user_engine
    engine.lexicon.user.add_custom_symbols("★")
    s = Session(engine)
    run(s, "ji3")
    goto(s, "我的符號")
    run(s, "1")
    _, v = run(s, "ap7")
    assert v.composition == "我★們"


def test_delete_removes_a_custom_symbol_from_the_panel(user_engine):
    engine = user_engine
    engine.lexicon.user.add_custom_symbols("★\n☆")
    s = Session(engine)
    goto(s, "我的符號")
    _, v = run(s, "{DEL}")
    assert v.candidates is not None  # stays open
    assert "已刪除" in v.notice
    assert engine.lexicon.user.custom_symbols() == ["☆"]


# ---------------------------------------------------------------- bugs found while building this
def test_tab_cycling_does_not_strand_the_opening_trigger(session):
    """Reported by reproduction, not by the user: Tab-cycling away from a
    "::"-opened panel and picking something used to leave the literal "::"
    sitting in the composition forever — _open_palette dropped trigger_at
    on every call. 'ji3::{TAB}1' used to produce '我::「'."""
    out, v = run(session, "ji3::{TAB}1")
    assert "::" not in (out + v.composition)

    out, v = run(session, "ji3::{TAB}{TAB}1")
    assert "::" not in (out + v.composition)


def test_tab_reached_snippet_list_can_be_filtered_by_typing(session):
    """片語's filter-by-typing used to only work when reached through the
    ;; trigger: Tab-browsing to it left snippet_at unset, so typing just
    closed the panel and typed the letter normally. Gating on which tab is
    open instead of on snippet_at fixes it."""
    goto(session, "片語")
    _, v = run(session, "a")
    assert v.candidates is not None
    _, v = run(session, "d")
    # second letter: this is the one that broke first (_refilter_snippets
    # silently dropped cand.palette on every call, closing the gate again
    # after exactly one letter)
    assert v.candidates is not None


def test_backspace_on_an_empty_tab_reached_filter_does_not_eat_unrelated_text(session):
    """Hotkey-opened, Tab-browsed to 片語 (no ";;" ever typed): trigger_at
    is None, so there is nothing to delete into. The naive version called
    _delete_unit(before=True) unconditionally and ate the preceding
    character of whatever was already on screen."""
    run(session, "su3cl3")  # 你好
    goto(session, "片語")
    _, v = run(session, "{BS}")
    assert v.composition == "你好"  # unchanged
    assert v.candidates is None  # panel closed, nothing more
