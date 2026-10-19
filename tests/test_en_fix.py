"""英文打錯自動更正 (engine/en_fix.py): finished English words with one
slip read as the word meant; real words, terms, names and your own words
never change."""

import pytest

from smartime.devtools.simulate import run
from smartime.engine import en_fix


@pytest.mark.parametrize("typed, meant", [
    ("teh", "the"), ("recieve", "receive"), ("becuase", "because"),  # misspellings in the word list
    ("wrold", "world"), ("langauge", "language"), ("meetign", "meeting"),  # two neighbours swapped
    ("deadlien", "deadline"), ("thye", "they"),  # a swap beats a dropped key (the)
    ("hellp", "help"), ("acount", "account"), ("scheudle", "schedule"),
])
def test_a_finished_word_with_one_slip_reads_as_the_word_meant(session, typed, meant):
    _, v = run(session, f"ji3 {typed} ")
    assert v.composition == f"我 {meant} "


def test_real_words_terms_and_names_stay(session):
    """Rare real words right next to common ones (wand/and, newt/new,
    tome/time), terms with a key that looks extra (scss/css, jsonl/json),
    names: autocorrect leaves them exactly as the decoder read them before."""
    words = ["wand", "newt", "tome", "form", "lien", "scss", "jsonl", "toml", "venv", "kubectl", "vscode",
             "Chou", "Hsinchu", "Fable", "mvp", "nginx", "pytest", "sklearn", "tsconfig"]

    decoder = session.engine.decoder  # shared by the whole test run: put it back

    def typed(on):
        decoder.en_fix = on
        try:
            out = []
            for word in words:
                session._reset_buffer()
                out.append(run(session, f"ji3 {word} ")[1].composition)
            return out
        finally:
            decoder.en_fix = True

    assert typed(True) == typed(False)
    assert "我 wand " in typed(True) and "我 kubectl " in typed(True)


def test_only_finished_words(session):
    # half a word while typing is left alone (gaug is gauge in a moment) ...
    _, v = run(session, "ji3 teh")
    assert v.composition == "我 teh"
    # ... and fixed once a space or punctuation ends it
    out, v = run(session, "{C-,}")
    assert out + v.composition == "我 the，"


def test_case_follows_the_word_as_typed(session):
    _, v = run(session, "Teh ")
    assert v.composition == "The "
    session._reset_buffer()
    _, v = run(session, "TEH ")  # all caps: an acronym or a name, not ours to touch
    assert v.composition == "TEH "


def test_the_fix_is_marked_and_said_once(session):
    from smartime.engine.panel import decode_panel

    _, v = run(session, "ji3 wrold ")
    assert v.hint_panel is not None and v.hint_panel.fixed == "wrold → world"
    col = next(c for c in decode_panel(session).columns if c.text == "world")
    assert col.keys == "wrold" and col.reordered  # amber ↺, like a reordered syllable
    _, v = run(session, "su3")
    assert v.hint_panel is None or not v.hint_panel.fixed


def test_down_gives_the_word_as_typed_and_it_is_kept_from_then_on(tmp_path):
    from smartime import paths
    from smartime.config import Config
    from smartime.engine.decoder import Decoder
    from smartime.engine.layouts import DACHEN
    from smartime.engine.lexicon import Lexicon
    from smartime.engine.session import Engine, Session
    from smartime.engine.userdict import UserDict

    user = UserDict(tmp_path / "user.db")
    lex = Lexicon(paths.system_db_path(), user)
    s = Session(Engine(lexicon=lex, layout=DACHEN, decoder=Decoder(lex, DACHEN), config=Config()))
    _, v = run(s, "ji3 wrold {DOWN}")
    assert v.candidates[:2] == ["world", "wrold"]  # the fix, then the word as typed
    out, _ = run(s, "2{ENTER}")
    assert out == "我 wrold "
    out, _ = run(s, "ji3 wrold {ENTER}")
    assert out == "我 wrold "  # yours now: never corrected again
    user.close()
    lex.close()


def test_down_offers_the_fix_when_it_was_not_applied(session):
    # the word at the end is never corrected (Enter sends what is on screen);
    # in correction mode it is one word, and ↓ has the fix
    _, v = run(session, "ji3 teh{ESC}")
    assert v.composition == "我 teh" and v.correcting
    _, v = run(session, "{DOWN}")
    assert v.candidates[1] == "the"


def test_the_setting_reaches_the_decoder(lexicon):
    from smartime.config import Config
    from smartime.engine.decoder import Decoder
    from smartime.engine.layouts import DACHEN

    d = Decoder(lexicon, DACHEN)  # its own: the shared one stays as it is
    cfg = Config()
    cfg.en_autocorrect = False
    d.apply_config(cfg)
    assert d.en_fix is False


def test_turned_off_it_types_as_typed(session):
    decoder = session.engine.decoder
    decoder.en_fix = False
    session.cfg.en_autocorrect = False
    try:
        _, v = run(session, "ji3 teh wrold ")
        assert v.composition == "我 teh wrold "
        _, v = run(session, "{DOWN}")
        assert "world" not in (v.candidates or [])  # off means off, ↓ included
    finally:
        decoder.en_fix = True
        session.cfg.en_autocorrect = True


def test_known_typos_are_typos():
    """Every fix is a word in the list, no typo is a common word itself, and
    no entry corrects a word to itself."""
    from smartime import paths
    from smartime.engine.lexicon import Lexicon

    lex = Lexicon(paths.system_db_path())
    for typo, fix in en_fix.KNOWN_TYPOS.items():
        assert typo != fix and lex.en_score(fix) is not None, (typo, fix)
        score = lex.en_score(typo)
        assert score is None or score < en_fix.EN_COMMON, typo
    lex.close()
