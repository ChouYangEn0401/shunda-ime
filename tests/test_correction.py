"""Correction mode (Esc while composing; Vim-like keys)."""

from smartime.devtools.simulate import run


def test_esc_enters_correction_and_second_esc_clears(session):
    out, v = run(session, "ji3ap7{ESC}")
    assert out == "" and v.composition == "我們" and v.correcting
    assert v.hint.startswith("【修正·國字】")
    out, v = run(session, "{ESC}")
    assert out == "" and v.composition == "" and not v.correcting


def test_correction_mode_can_be_turned_off(session):
    session.cfg.correction_mode = False
    _, v = run(session, "ji3ap7{ESC}")
    assert v.composition == ""


def test_cursor_lands_on_last_character_and_moves_with_h_l(session):
    _, v = run(session, "ji3e/4dj94{ESC}")
    assert v.cursor == 2 and "快" in v.hint
    _, v = run(session, "hh")
    assert v.cursor == 0 and "我" in v.hint
    _, v = run(session, "h")  # stays on the first character
    assert v.cursor == 0
    _, v = run(session, "llll")  # and on the last
    assert v.cursor == 2


def test_views_text_zhuyin_keys(session):
    # the composition keeps the real text; the other views are in the hint
    _, v = run(session, "ji3e/4dj94{ESC}v")
    assert v.layer == "zhuyin" and v.composition == "我更快"
    assert "ㄨㄛˇ ㄍㄥˋ ［ㄎㄨㄞˋ］" in v.hint
    _, v = run(session, "v")
    assert v.layer == "keys" and v.composition == "我更快"
    assert "ji3e/4［d］j94" in v.hint
    _, v = run(session, "v")
    assert v.layer == "text" and v.composition == "我更快"


def test_keys_view_shows_and_deletes_a_stray_key(session):
    # the stray "e" was dropped silently; the 按鍵 view shows it
    _, v = run(session, "ji3ee/4dj94{ESC}vv")
    assert v.composition == "我更快"
    # go to key 3 (the stray e) and delete just that key
    run(session, "{HOME}lll")
    _, v = run(session, "")
    assert "ji3［e］e/4dj94" in v.hint and "被略過的鍵" in v.hint
    _, v = run(session, "xv")  # 按鍵 -> 國字
    assert v.layer == "text" and v.composition == "我更快"
    assert "".join(k.char for k in session.keys) == "ji3e/4dj94"


def test_x_deletes_the_character_under_the_cursor(session):
    _, v = run(session, "ji3k27{ESC}hx")
    assert v.composition == "的" and v.correcting


def test_j_k_cycle_candidates_in_place_and_u_undoes(session):
    _, v = run(session, "ji3a87{ESC}j")
    assert v.composition == "我嘛" and v.correcting
    _, v = run(session, "k")
    assert v.composition == "我嗎"
    _, v = run(session, "jj")
    assert v.composition != "我嘛"
    _, v = run(session, "u")
    assert v.composition == "我嗎"


def test_e_switches_chinese_and_raw_keys(session):
    _, v = run(session, "mvp {ESC}e")
    assert v.composition == "勳"
    _, v = run(session, "e")
    assert v.composition == "mvp "
    _, v = run(session, "{ESC}{ESC}ji3k27{ESC}e")
    assert v.composition == "我k27"


def test_r_retypes_one_character(session):
    _, v = run(session, "ji3k27{ESC}hr")
    assert not v.correcting and v.composition == "的"
    _, v = run(session, "su3")
    assert v.composition == "你的"


def test_i_returns_to_typing_before_the_character(session):
    _, v = run(session, "ji3k27{ESC}i283")
    assert not v.correcting and v.composition == "我打的"


def test_enter_commits_from_correction_mode(session):
    out, v = run(session, "ji3a87{ESC}j{ENTER}")
    assert out == "我嘛" and v.composition == "" and not v.correcting


def test_unknown_key_shows_help_instead_of_typing(session):
    _, v = run(session, "ji3{ESC}z")
    assert v.composition == "我" and "修正模式" in v.notice


def test_cycling_learns_only_the_final_choice(tmp_path):
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
    run(s, "ji3a87{ESC}jjj{ENTER}")
    learned = [r["phrase"] for r in user.list(source="learned")]
    assert len(learned) == 1
    user.close()
    lex.close()
