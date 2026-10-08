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
    assert p.layout == "list" and p.chip == "顏文字"
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
