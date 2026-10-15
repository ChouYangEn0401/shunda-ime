"""修字練習: every level is a real mistake with a fix that works, and
practising never teaches the IME anything."""

import re

import pytest

from smartime import practice
from smartime.devtools.keyscript import script_for
from smartime.devtools.simulate import run


def _expand(session, fix: str) -> str:
    """Run a level's fix: {T:熱} types 熱, {T:ˋ} is that tone's key, {PICK:帶}
    picks that candidate by its number. Returns what Enter commits."""
    engine = session.engine
    for part in re.split(r"(\{(?:T|PICK):[^}]+\})", fix):
        if part.startswith("{T:"):
            arg = part[3:-1]
            if arg in "ˊˇˋ˙":
                part = next(c for c in "1234567890-=qwertyuiop[]asdfghjkl;'zxcvbnm,./ "
                            if engine.layout.tone(c) == arg)
            else:
                part = script_for(arg, engine.lexicon, engine.layout)
        elif part.startswith("{PICK:"):
            _, v = run(session, "")
            want = part[6:-1]
            assert v.candidates and want in v.candidates, (want, v.candidates)
            part = str(v.candidates.index(want) % session.cand.page_size + 1)
        if part:
            run(session, part)
    out, _ = run(session, "{ENTER}")
    return out


@pytest.mark.parametrize("level", practice.LEVELS, ids=[lv.id for lv in practice.LEVELS])
def test_every_level_is_a_real_mistake_and_its_hint_fixes_it(session, level):
    keys = script_for(level.type_text, session.engine.lexicon, session.engine.layout)
    _, v = run(session, keys)
    assert v.composition == level.wrong, "the IME no longer makes this mistake: pick another sentence"
    assert _expand(session, level.fix) == level.target


def test_levels_have_unique_ids_and_say_what_to_press():
    ids = [lv.id for lv in practice.LEVELS]
    assert len(ids) == len(set(ids))
    for lv in practice.LEVELS:
        assert "<kbd>" in lv.hint and lv.target and lv.title


def test_nothing_is_learned_while_practising(tmp_path):
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
    try:
        practice.set_active(True)
        run(s, "ru42k6294m3n03{ESC}hh{DOWN}3{ENTER}")  # 代 -> 帶, a choice that would be learned
        assert user.count() == 0
        _, v = run(s, "ji3{ESC}a")
        assert "練習中" in v.notice and user.count() == 0
        run(s, "{ENTER}")
        practice.set_active(False)
        run(s, "ru42k6294m3n03{ESC}hh{DOWN}3{ENTER}")
        assert user.count() > 0  # and afterwards it learns again
    finally:
        user.close()
        lex.close()


def test_the_practising_flag_lapses_by_itself(monkeypatch):
    practice.set_active(True)
    assert practice.active()
    now = practice.time.time()
    monkeypatch.setattr(practice.time, "time", lambda: now + practice.ACTIVE_SECONDS + 1)
    assert not practice.active()  # a page that closed cannot leave the IME not learning


def test_progress_is_kept(tmp_path):
    assert practice.done() == []
    practice.mark_done("swap")
    practice.mark_done("swap")
    practice.mark_done("no-such-level")
    assert practice.done() == ["swap"]


def test_settings_api_gives_the_keys_for_the_users_layout(tmp_path):
    from smartime.config import Config
    from smartime.settings.api import SettingsApp

    app = SettingsApp()
    try:
        levels = app.practice_state()["levels"]
        assert levels[0]["keys"] == "su3vu0 y.318 "  # 你先走吧 on 大千
        cfg = Config.load(app.config_path)
        cfg.layout = "eten"
        cfg.save(app.config_path)
        assert app.practice_state()["levels"][0]["keys"] != levels[0]["keys"]
        assert app.practice_done({"id": "swap"})["done"] == ["swap"]
        app.practice_active({"on": True})
        assert practice.active()
        app.practice_active({"on": False})
        assert not practice.active()
    finally:
        app.close()
