from smartime.devtools.simulate import run
from smartime.engine.session import Mode


def test_letters_show_raw_with_zhuyin_hint(session):
    _, v = run(session, "u.")
    assert v.composition == "u."
    assert v.hint == "ㄧㄡ"


def test_tone_key_converts(session):
    _, v = run(session, "ji3ap7")
    assert v.composition == "我們"
    assert v.cursor == 2
    assert v.hint == ""


def test_enter_commits_buffer(session):
    out, v = run(session, "ji3ap7{ENTER}")
    assert out == "我們"
    assert v.composition == ""


def test_clause_punctuation_commits(session):
    out, v = run(session, "su3cl3<")
    assert out == "你好，"
    assert v.composition == ""


def test_shifted_punct_alone_commits_fullwidth(session):
    out, _ = run(session, "?")
    assert out == "？"


def test_backspace_removes_whole_syllable(session):
    _, v = run(session, "ji3ap7{BS}")
    assert v.composition == "我"


def test_backspace_in_unfinished_syllable_removes_one_key(session):
    _, v = run(session, "ji3u.{BS}")
    assert v.composition == "我u"
    assert v.hint == "ㄧ"


def test_escape_clears_without_commit(session):
    out, v = run(session, "ji3ap7{ESC}")
    assert out == ""
    assert v.composition == ""


def test_candidates_at_end_and_select(session):
    _, v = run(session, "ji3ap7{DOWN}")
    assert v.candidates[0] == "我們"
    assert "們" in v.candidates
    _, v = run(session, str(v.candidates.index("們") + 1))
    assert v.candidates is None
    assert v.composition == "我們"


def test_candidate_for_char_after_cursor(session):
    _, v = run(session, "ji3a87{LEFT}{UP}")
    assert v.cursor == 1
    assert v.candidates[0] == "嗎"
    _, v = run(session, "2")  # choose 嘛
    assert v.composition == "我" + v.composition[1]
    assert v.composition != "我嗎"


def test_pinned_choice_survives_more_typing(session):
    run(session, "ji3a87{DOWN}")
    _, v = run(session, "{DOWN}{ENTER}")  # move highlight to the 2nd candidate and pick it
    chosen = v.composition
    _, v = run(session, "su3")
    assert v.composition.startswith(chosen)


def test_escape_closes_candidates_only(session):
    _, v = run(session, "ji3ap7{DOWN}{ESC}")
    assert v.candidates is None
    assert v.composition == "我們"


def test_cursor_editing_inserts_in_middle(session):
    _, v = run(session, "ji3cl3{LEFT}")
    assert v.cursor == 1
    _, v = run(session, "ap7")
    assert v.composition == "我們好"


def test_tab_accepts_suggestion(session):
    _, v = run(session, "ao6u.3")
    assert v.composition == "沒有"
    assert v.suggestion
    expected = v.composition + v.suggestion
    _, v = run(session, "{TAB}")
    assert v.composition == expected


def test_shift_tap_toggles_english_mode(session):
    out, v = run(session, "{SHIFT}ji3")
    assert v.mode is Mode.ENGLISH
    assert out == "ji3"  # passed through to the app
    _, v = run(session, "{SHIFT}")
    assert v.mode is Mode.MIXED


def test_shift_toggle_commits_pending_text(session):
    out, _ = run(session, "ji3{SHIFT}")
    assert out == "我"


def test_space_and_enter_pass_through_when_idle(session):
    out, v = run(session, " ")
    assert out == " "
    assert v.composition == ""


def test_overflow_commits_oldest_text(session, engine):
    engine.config.max_buffer_chars = 4
    out, v = run(session, "ji3ap7ji3ap7ji3")
    assert out.startswith("我們")
    assert len(v.composition) <= 4
