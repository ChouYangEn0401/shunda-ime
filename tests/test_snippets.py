"""片語 (;; + keyword, preview, Enter types it) and 顏文字 (user feedback #7, #10)."""

import pytest

from smartime.engine.symbols import TABS
from smartime.devtools.simulate import run
from smartime.engine.panel import candidate_panel


@pytest.fixture
def snip_session(tmp_path):
    from smartime import paths
    from smartime.config import Config
    from smartime.engine.decoder import Decoder
    from smartime.engine.layouts import DACHEN
    from smartime.engine.lexicon import Lexicon
    from smartime.engine.session import Engine, Session
    from smartime.engine.symbols import SymbolPanel
    from smartime.engine.userdict import UserDict

    user = UserDict(tmp_path / "user.db")
    user.add_snippet("範例市範例區示範路 100 號\n（請寄到這裡）", "我的地址", "addr")
    user.add_snippet("感謝您的來信！", "", "thanks")
    lex = Lexicon(paths.system_db_path(), user)
    engine = Engine(lexicon=lex, layout=DACHEN, decoder=Decoder(lex, DACHEN), config=Config(),
                    symbols=SymbolPanel(tmp_path / "recent.json"))
    yield Session(engine)
    user.close()
    lex.close()


def test_double_semicolon_lists_snippets_with_a_preview(snip_session):
    _, v = run(snip_session, ";;")
    assert v.candidates[:2] == ["我的地址", "感謝您的來信！"]
    p = candidate_panel(snip_session)
    assert p.snippet and p.preview.startswith("範例市")
    _, v = run(snip_session, "{DOWN}")
    assert candidate_panel(snip_session).preview == "感謝您的來信！"


def test_keyword_filters_and_enter_types_the_whole_text(snip_session):
    _, v = run(snip_session, "ji3;;th")
    assert v.composition == "我;;th" and v.candidates == ["感謝您的來信！"]
    out, v = run(snip_session, "{ENTER}")
    assert out == "我感謝您的來信！" and v.composition == ""
    assert snip_session.engine.user.snippets()[1]["count"] == 1


def test_digit_picks_and_multiline_text_is_typed_as_is(snip_session):
    out, _ = run(snip_session, ";;1")
    assert out == "範例市範例區示範路 100 號\n（請寄到這裡）"


def test_esc_keeps_what_was_typed_and_backspace_edits_the_filter(snip_session):
    _, v = run(snip_session, ";;ad")
    assert v.candidates == ["我的地址"]
    _, v = run(snip_session, "{BS}{BS}")
    assert v.composition == ";;" and len(v.candidates) == 2
    _, v = run(snip_session, "{BS}")  # empty filter: the list closes, one ; is removed
    assert v.candidates is None and v.composition == ";"
    _, v = run(snip_session, ";x{ESC}")
    assert v.candidates is None and v.composition == ";;x"


def test_trigger_can_be_turned_off(snip_session):
    snip_session.cfg.snippet_trigger = ""
    _, v = run(snip_session, ";;")
    assert v.candidates is None


def test_snippets_and_kaomoji_tabs_in_the_symbol_panel(snip_session):
    from smartime.engine.symbols import TABS

    run(snip_session, "{RCTRL}")
    for _ in range(TABS.index("顏文字")):
        run(snip_session, "{TAB}")
    assert TABS[snip_session.cand.palette] == "顏文字"
    p = candidate_panel(snip_session)
    assert p.chip == "顏文字"
    face = snip_session.cand.current.text
    out, _ = run(snip_session, "{ENTER}")
    assert out == face
    # used once: listed first next time
    run(snip_session, "{RCTRL}")
    for _ in range(TABS.index("顏文字")):
        run(snip_session, "{TAB}")
    assert snip_session.cand.items[0].text == face and snip_session.cand.items[0].group == "最近"
    run(snip_session, "{ESC}")
    run(snip_session, "{RCTRL}")
    for _ in range(TABS.index("片語")):
        run(snip_session, "{TAB}")
    v = snip_session.view()
    assert TABS[snip_session.cand.palette] == "片語"
    assert v.candidates[0] == "我的地址"


def test_recent_symbols_are_saved_by_the_real_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTIME_USER_DIR", str(tmp_path / "u"))
    from smartime.pime.server import build_engine

    engine = build_engine()
    assert engine.symbols.path is not None and engine.symbols.path.name == "recent-symbols.json"
    engine.lexicon.user.close()
    engine.lexicon.close()


def test_palette_opens_with_the_text_trigger(session):
    """:: opens the symbol panel the same way ;; opens 片語 — asked for
    because the hotkey alone was not discoverable (and right Alt, which the
    user had configured, never reaches an input method in some apps)."""
    _, v = run(session, "ji3::")
    assert v.candidates is not None and session.cand.palette == 0
    _, v = run(session, "{S-TAB}")  # one step back: 顏文字
    assert session.cand.palette == len(TABS) - 1


def test_trigger_does_not_fire_inside_an_english_token(engine):
    """C++ scope operator: std::vector must stay text.

    The decoder has to follow the config here — with the default "keycap"
    style ``:`` types the half-width colon, which is not clause punctuation,
    so the whole token stays in one buffer.
    """
    from smartime.config import Config
    from smartime.engine.session import Session

    engine.config = Config()
    engine.decoder.apply_config(engine.config)
    try:
        s = Session(engine)
        _, v = run(s, "std::")
        assert v.candidates is None and v.composition == "std::"
        _, v = run(s, "vector")
        assert v.composition == "std::vector"
    finally:
        engine.decoder.apply_config(Config.from_dict({"punct_style": "custom", "halfwidth_symbols": '"'}))


def test_picking_a_symbol_removes_the_trigger(session):
    out, _ = run(session, "ji3::")
    wanted = session.cand.page_items()[2].text
    more, v = run(session, "3")
    # the :: itself is never typed, only the symbol
    assert out + more + v.composition == "我" + wanted


# ---------------------------------------------------------------- managing many (settings page)

def test_snippet_category_bulk_delete_and_move_to_the_ends(tmp_path):
    from smartime.engine.userdict import UserDict

    u = UserDict(tmp_path / "user.db")
    a = u.add_snippet("家裡地址", "家", "addr", "地址")
    b = u.add_snippet("公司地址", "公司", "addr")
    c = u.add_snippet("謝謝", "", "ty")
    d = u.add_snippet("好的", "", "ok")
    assert [r["category"] for r in u.snippets()] == ["地址", "", "", ""]
    assert u.set_snippets_category([b, c], " 常用 ") == 2
    assert {r["id"]: r["category"] for r in u.snippets()}[b] == "常用"
    u.update_snippet(d, category="客服")
    u.move_snippet(d, -1_000_000)
    u.move_snippet(a, 1_000_000)
    assert [r["id"] for r in u.snippets()] == [d, b, c, a]
    assert u.delete_snippets([b, c, 999]) == 2
    assert [r["id"] for r in u.snippets()] == [d, a]
    u.close()


def test_the_category_does_not_change_the_double_semicolon_list(snip_session):
    """分類 is for the settings page only: ;; keeps the user's order and
    filters by keyword exactly as before."""
    user = snip_session.engine.user
    user.set_snippets_category([r["id"] for r in user.snippets()], "客服")
    _, v = run(snip_session, ";;")
    assert v.candidates[:2] == ["我的地址", "感謝您的來信！"]
    _, v = run(snip_session, "th")
    assert v.candidates == ["感謝您的來信！"]


def test_schema_2_dictionary_gets_the_snippet_category_and_keeps_its_snippets(tmp_path):
    import sqlite3

    from smartime.engine.userdict import SCHEMA_VERSION, UserDict

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO meta VALUES ('schema', '2');"
        "CREATE TABLE snippets (id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '',"
        " keyword TEXT NOT NULL DEFAULT '', body TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0,"
        " count INTEGER NOT NULL DEFAULT 0, last_used REAL, created REAL NOT NULL);"
        "INSERT INTO snippets (title, keyword, body, sort, count, created) VALUES ('地址', 'addr', '台北市', 1, 4, 1);")
    con.commit()
    con.close()
    u = UserDict(path)
    rows = u.snippets()
    assert [(r["keyword"], r["body"], r["count"], r["category"]) for r in rows] == [("addr", "台北市", 4, "")]
    assert u._con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == str(SCHEMA_VERSION)
    u.add_snippet("謝謝", "", "ty", "客服")
    assert [r["category"] for r in u.snippets()] == ["", "客服"]
    u.close()


def test_merging_another_pcs_snippets_carries_their_category(tmp_path):
    import sqlite3

    from smartime.engine.userdict import UserDict

    laptop = UserDict(tmp_path / "laptop" / "user.db")
    laptop.add_snippet("公司地址", "公司", "addr", "地址")
    laptop.add_snippet("謝謝您", "", "ty", "客服")
    laptop.add_snippet("我的版本", "", "mine", "別台的分類")
    snap = tmp_path / "laptop.db"
    laptop.backup_to(snap)
    laptop.close()

    mine = UserDict(tmp_path / "mine" / "user.db")
    mine.add_snippet("謝謝您", "", "ty")  # same text, no 分類 here: takes the laptop's
    mine.add_snippet("我的版本", "", "mine", "我的分類")  # mine has one: kept
    report = mine.merge_from(snap)
    assert report["snippets"] == 1
    cats = {r["body"]: r["category"] for r in mine.snippets()}
    assert cats == {"謝謝您": "客服", "我的版本": "我的分類", "公司地址": "地址"}

    # an export from before 分類 existed still merges
    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    con.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO meta VALUES ('schema', '2');"
        "CREATE TABLE snippets (id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '',"
        " keyword TEXT NOT NULL DEFAULT '', body TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0,"
        " count INTEGER NOT NULL DEFAULT 0, last_used REAL, created REAL NOT NULL);"
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, sort INTEGER NOT NULL DEFAULT 0);"
        "CREATE TABLE entries (id INTEGER PRIMARY KEY, phrase TEXT NOT NULL, reading TEXT NOT NULL DEFAULT '',"
        " kind TEXT NOT NULL DEFAULT 'zh', category_id INTEGER, source TEXT NOT NULL DEFAULT 'learned',"
        " count INTEGER NOT NULL DEFAULT 0, last_used REAL, created REAL NOT NULL,"
        " blocked INTEGER NOT NULL DEFAULT 0, UNIQUE (phrase, reading));"
        "INSERT INTO snippets (title, keyword, body, sort, created) VALUES ('', 'bye', '再見', 1, 1);")
    con.commit()
    con.close()
    assert mine.merge_from(old)["snippets"] == 1
    assert {r["body"]: r["category"] for r in mine.snippets()}["再見"] == ""
    mine.close()
