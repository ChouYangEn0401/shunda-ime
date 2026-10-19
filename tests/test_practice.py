"""練習場: every task can be passed exactly as its instructions say, every
mistake it shows is real, and practising never teaches the IME anything."""

import re

import pytest

from smartime import practice
from smartime.devtools.keyscript import script_for
from smartime.devtools.simulate import run

TASKS = [s for s in practice.STEPS if s.kind == "task"]
TIPS = [s for s in practice.STEPS if s.kind == "tip"]


def _expand(session, fix: str) -> str:
    """Run a step's fix: {T:熱} types 熱, {T:ˋ} is that tone's key, {PICK:帶}
    picks that candidate by its number. Returns everything committed,
    including by the final Enter."""
    engine = session.engine
    committed = ""
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
            out, _ = run(session, part)
            committed += out
    out, _ = run(session, "{ENTER}")
    return committed + out


@pytest.mark.parametrize("step", TASKS, ids=[s.id for s in TASKS])
def test_every_task_is_passed_by_doing_what_it_says(session, step):
    keys = practice.step_keys(step, session.engine.lexicon, session.engine.layout)
    out, v = run(session, keys)
    if step.wrong:
        assert v.composition == step.wrong, "the IME no longer makes this mistake: pick another sentence"
    assert (out + _expand(session, step.fix)).strip() == step.target


def test_steps_are_well_formed():
    ids = [s.id for s in practice.STEPS]
    assert len(ids) == len(set(ids))
    chapters = {c.id for c in practice.CHAPTERS}
    for s in practice.STEPS:
        assert s.chapter in chapters and s.title and s.hook and s.how
        if s.kind == "task":
            assert s.target and (s.type_text or s.keys)
        else:
            assert s.kind == "tip" and not s.target
    # every chapter has something in it, and the tour starts by switching over
    assert all(any(s.chapter == c.id for s in practice.STEPS) for c in practice.CHAPTERS)
    assert practice.STEPS[0].id == "hello"


def test_the_correction_chapter_covers_the_keys_the_panel_lists():
    """What the help row's first line names is taught somewhere in the tour."""
    text = " ".join(s.hook + s.how + s.pro for s in practice.STEPS if s.chapter == "fix")
    for key in ("<kbd>←</kbd>", "<kbd>↓</kbd>", "<kbd>j</kbd>", "<kbd>r</kbd>", "<kbd>x</kbd>", "<kbd>u</kbd>",
                "<kbd>Enter</kbd>", "<kbd>Esc</kbd>", "<kbd>Shift</kbd>+<kbd>←</kbd>"):
        assert key in text, key


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


def test_progress_is_kept_and_can_be_reset(tmp_path):
    assert practice.done() == []
    practice.mark_done("swap")
    practice.mark_done("swap")
    practice.mark_done("legend")  # a tip counts too
    practice.mark_done("no-such-step")
    assert practice.done() == ["swap", "legend"]
    assert practice.reset() == [] and practice.done() == []


def test_settings_api_gives_the_tour_with_keys_for_the_users_layout(tmp_path):
    from smartime.config import Config
    from smartime.settings.api import SettingsApp

    app = SettingsApp()
    try:
        state = app.practice_state()
        steps = {s["id"]: s for c in state["chapters"] for s in c["steps"]}
        assert [c["id"] for c in state["chapters"]] == [c.id for c in practice.CHAPTERS]
        assert steps["swap"]["keys"] == "su3vu0 y.318 " and steps["swap"]["show_keys"]  # 你先走吧 on 大千
        assert steps["symbol"]["keys"] == "::{TAB}1" and not steps["symbol"]["show_keys"]
        assert steps["legend"]["kind"] == "tip" and steps["legend"]["keys"] == ""
        cfg = Config.load(app.config_path)
        cfg.layout = "eten"
        cfg.save(app.config_path)
        again = {s["id"]: s for c in app.practice_state()["chapters"] for s in c["steps"]}
        assert again["swap"]["keys"] != steps["swap"]["keys"]
        assert app.practice_done({"id": "swap"})["done"] == ["swap"]
        assert app.practice_reset()["done"] == []
        app.practice_active({"on": True})
        assert practice.active()
        app.practice_active({"on": False})
        assert not practice.active()
    finally:
        app.close()


def test_progress_travels_with_the_export_file(tmp_path):
    practice.mark_done("hello")
    assert practice.export_data() == {"done": ["hello"]}
    # another machine's file: a union, unknown ids ignored, nothing taken away
    assert practice.merge_done(["swap", "hello", "no-such-step", 7]) == ["hello", "swap"]
    assert practice.merge_done("junk") == ["hello", "swap"]
