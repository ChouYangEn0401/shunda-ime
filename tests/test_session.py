from smartime.devtools.simulate import run
from smartime.engine.session import Mode


def test_letters_show_raw_with_zhuyin_hint(session):
    _, v = run(session, "u.")
    assert v.composition == "u."
    assert v.hint == "ㄧㄡ"


def test_hint_shows_canonical_order_for_swapped_keys(session):
    # typing ㄜ then ㄉ (fast-typing order) hints the syllable it will become
    _, v = run(session, "k2")
    assert v.hint == "ㄉㄜ"


def test_tone_key_converts(session):
    _, v = run(session, "ji3ap7")
    assert v.composition == "我們"
    assert v.cursor == 2
    assert v.hint == ""


def test_enter_commits_buffer(session):
    out, v = run(session, "ji3ap7{ENTER}")
    assert out == "我們"
    assert v.composition == ""


def test_double_quote_is_halfwidth(session):
    _, v = run(session, 'ji3ap7"python"')
    assert v.composition == '我們"python"'


def test_clause_punctuation_commits(session):
    out, v = run(session, "su3cl3<")
    assert out == "你好，"
    assert v.composition == ""
    out, _ = run(session, "?")
    assert out == "？"


def test_punctuation_variants_in_candidates(session):
    # the other width and related symbols are one ↓ away
    _, v = run(session, '"{DOWN}')
    assert v.candidates[:3] == ['"', "；", "“"]
    assert "「" in v.candidates


def test_english_token_offers_chinese_readings(session):
    # mvp stays English, but 勳 is one pick away
    _, v = run(session, "mvp {DOWN}")
    assert v.candidates[0] == "mvp"
    assert "勳" in v.candidates


def test_chinese_offers_raw_keys(session):
    # ㄟ decoded from "o␣" can be turned back into the letters typed
    _, v = run(session, "o {DOWN}")
    assert "o " in v.candidates


def test_hint_shows_reading_and_keys_when_cursor_moved_back(session):
    # stray "e" (left by fast typing) is dropped and pointed out
    _, v = run(session, "ji3ee/4dj94{LEFT}{LEFT}")
    assert v.composition == "我更快"
    assert "ㄍㄥˋ" in v.hint and "e/4" in v.hint and "略過 e" in v.hint


def test_hint_names_a_key_just_dropped(session):
    # a stray key is no longer removed silently (reported: "pup" -> "up"
    # without any sign of the dropped p)
    _, v = run(session, "ji3ee/4")
    assert v.composition == "我更"
    assert "略過 e" in v.hint


def test_hint_shows_the_character_in_its_sentence_when_moving_back(session):
    # reported: hard to see which character is being fixed
    _, v = run(session, "ji3ap7rup wu0 cl3{LEFT}{LEFT}")
    assert "［天］" in v.hint and "今" in v.hint and "好" in v.hint
    assert "ㄊㄧㄢ" in v.hint


def test_backspace_next_to_dropped_key_removes_visible_char(session):
    _, v = run(session, "ji3ee/4{LEFT}{BS}")
    assert v.composition == "更"


def test_backspace_removes_whole_syllable(session):
    _, v = run(session, "ji3ap7{BS}")
    assert v.composition == "我"


def test_backspace_in_unfinished_syllable_removes_one_key(session):
    _, v = run(session, "ji3u.{BS}")
    assert v.composition == "我u"
    assert v.hint == "ㄧ"


def test_escape_twice_clears_without_commit(session):
    # the first Esc enters correction mode (tests/test_correction.py)
    out, v = run(session, "ji3ap7{ESC}{ESC}")
    assert out == ""
    assert v.composition == ""


def test_candidates_at_end_and_select(session):
    _, v = run(session, "ji3ap7{DOWN}")
    assert v.candidates[0] == "我們"
    assert "們" in v.candidates
    _, v = run(session, str(v.candidates.index("們") + 1))
    assert v.candidates is None
    assert v.composition == "我們"


def test_numpad_digits_select_candidates(session):
    # reported: the number keys beside the keyboard did nothing in the
    # candidate window (only the 1-9 above the letters worked)
    from smartime.devtools.simulate import press
    from smartime.engine.keys import KeyInput

    _, v = run(session, "ji3ap7{DOWN}")
    index = v.candidates.index("們")
    numpad = KeyInput(vk=0x60 + index + 1, char=str(index + 1))  # VK_NUMPAD1..9
    handled, v = press(session, numpad)
    assert handled and v.candidates is None
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
    session.cfg.shift_cycle = "two"
    out, v = run(session, "{SHIFT}ji3")
    assert v.mode is Mode.ENGLISH
    assert out == "ji3"  # passed through to the app
    _, v = run(session, "{SHIFT}")
    assert v.mode is Mode.AUTO


def test_pure_chinese_mode_never_outputs_english(session):
    session.set_mode(Mode.CHINESE)
    _, v = run(session, "mvp ")
    assert v.composition == "勳"  # in 中英自動 this stays "mvp "
    run(session, "{ENTER}")
    _, v = run(session, "283")
    assert v.composition == "打"  # top-row digits are zhuyin, never numbers


def test_shift_returns_to_last_chinese_side_mode(session):
    session.cfg.shift_cycle = "two"
    session.set_mode(Mode.CHINESE)
    _, v = run(session, "{SHIFT}")
    assert v.mode is Mode.ENGLISH
    _, v = run(session, "{SHIFT}")
    assert v.mode is Mode.CHINESE


def test_shift_cycles_through_three_modes_by_default(session):
    # requested: Shift reaches 英文, 中文 and 自動
    modes = []
    for _ in range(3):
        _, v = run(session, "{SHIFT}")
        modes.append(v.mode)
    assert modes == [Mode.CHINESE, Mode.ENGLISH, Mode.AUTO]


def test_set_mode_commits_pending_text(session):
    out, _ = run(session, "ji3")
    session.set_mode(Mode.CHINESE)
    assert session.view().commit == "我"


def test_shift_toggle_commits_pending_text(session):
    out, _ = run(session, "ji3{SHIFT}")
    assert out == "我"


def test_space_and_enter_pass_through_when_idle(session):
    out, v = run(session, " ")
    assert out == " "
    assert v.composition == ""


def test_ctrl_punctuation_commits_clause(session):
    # 微軟新注音 / 華碩 convention; previously passed to the app (VS Code
    # opened Settings on Ctrl+, and Quick Fix on Ctrl+.)
    out, v = run(session, "su3cl3{C-,}")
    assert out == "你好，"
    assert v.composition == ""


def test_ctrl_punctuation_when_idle_and_with_shift(session):
    out, _ = run(session, "{C-.}{CS-/}{CS-1}")
    assert out == "。？！"


def test_ctrl_bracket_stays_in_composition(session):
    _, v = run(session, "{C-[}ji3{C-]}")
    assert v.composition == "「我」"


def test_ctrl_punctuation_passes_through_in_english_mode(session):
    from smartime.devtools.simulate import press
    from smartime.engine.keys import VK_OEM_COMMA, KeyInput

    session.set_mode(Mode.ENGLISH)
    handled, _ = press(session, KeyInput(vk=VK_OEM_COMMA, ctrl=True))
    assert handled is False


def test_ctrl_other_keys_still_pass_through(session):
    from smartime.devtools.simulate import press
    from smartime.engine.keys import KeyInput

    handled, _ = press(session, KeyInput(vk=ord("C"), ctrl=True))  # Ctrl+C
    assert handled is False


def test_overflow_commits_oldest_text(session, engine):
    engine.config.max_buffer_chars = 4
    out, v = run(session, "ji3ap7ji3ap7ji3")
    assert out.startswith("我們")
    assert len(v.composition) <= 4


def test_text_typed_by_programs_passes_through(session):
    # VK_PACKET = a Unicode character from SendInput (voice input, paste tools)
    from smartime.engine.keys import VK_PACKET, KeyInput

    assert not session.filter_key_down(KeyInput(vk=VK_PACKET, char="我"))
    run(session, "ji3")
    assert not session.filter_key_down(KeyInput(vk=VK_PACKET, char="a"))
