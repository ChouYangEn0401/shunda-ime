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


def test_clause_punctuation_commits_everything_before_it(session):
    # The sentence is sent as soon as the clause ends, but the mark itself
    # stays in the composition: it is the one character you may still want
    # to change the width of (↓ offers ，/,), and committing it made that
    # impossible. Reported: 「標點沒辦法透過『下』去操作」.
    out, v = run(session, "su3cl3<")
    assert out == "你好" and v.composition == "，"
    _, v = run(session, "{DOWN}")
    assert "," in v.candidates
    out, v = run(session, "{ESC}?")
    assert out + v.composition == "，？"


def test_punctuation_variants_in_candidates(session):
    # the other width and related symbols are one ↓ away
    _, v = run(session, '"{DOWN}')
    assert v.candidates[:3] == ['"', "＂", "“"] and "；" in v.candidates
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
    # Esc enters correction mode (tests/test_correction.py); D twice clears
    out, v = run(session, "ji3ap7{ESC}DD")
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
    assert out == "你好" and v.composition == "，"


def test_ctrl_punctuation_when_idle_and_with_shift(session):
    out, v = run(session, "{C-.}{CS-/}{CS-1}")
    assert out + v.composition == "。？！"


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
    # while composing it is taken only to commit the composition first, then
    # passed on (so dictated text lands after it, not inside it)
    packet = KeyInput(vk=VK_PACKET, char="a")
    assert session.filter_key_down(packet)
    assert session.key_down(packet) is False
    v = session.view()
    assert v.commit == "我" and v.composition == ""


def test_keys_for_the_app_commit_the_composition_first(session):
    # Regression (#5): Ctrl+V while text was still composing pasted into the
    # middle of the composition / left odd formatting. Every key we do not
    # handle that acts on the document commits first, then reaches the app.
    from smartime.devtools.simulate import press
    from smartime.engine.keys import KeyInput

    for key in (KeyInput(vk=ord("V"), ctrl=True), KeyInput(vk=ord("S"), ctrl=True),
                KeyInput(vk=0x0D, ctrl=True),  # Ctrl+Enter (send in chat apps)
                KeyInput(vk=0x74),  # F5
                KeyInput(vk=0x2D, shift=True)):  # Shift+Insert (paste)
        run(session, "ji3ap7")
        handled, v = press(session, key)
        assert handled is False, key
        assert v.commit == "我們" and v.composition == "", key


def test_media_keys_do_not_commit(session):
    from smartime.engine.keys import KeyInput

    run(session, "ji3")
    assert not session.filter_key_down(KeyInput(vk=0xAF))  # volume up
    assert session.composing


# ---- Backspace removes exactly one visible character (#4) -----------------
# Cases from the user's real typing log (2026-10-02): a hidden stray key came
# back after Backspace (`…顯d` -> `…顯g`), or one Backspace removed two
# letters because the rest was decoded again.

def test_backspace_takes_the_hidden_stray_key_with_the_character(session):
    _, v = run(session, "ji3yu")
    assert v.composition == "我u" and "略過 y" in v.hint
    _, v = run(session, "{BS}")
    assert v.composition == "我"  # not 我y
    assert [k.char for k in session.keys] == list("ji3")


def test_backspace_never_changes_the_other_characters(session):
    _, v = run(session, "ji3wjk27{LEFT}{BS}")
    assert v.composition == "我w的"  # not 我的 (w turned into a hidden key)


def test_backspace_does_not_merge_neighbours_into_another_word(session):
    _, v = run(session, "rup kjg6c.4")
    assert v.composition == "今kj時候"
    _, v = run(session, "{LEFT}{BS}")
    assert v.composition == "今kj候"  # 時 removed; k j keep their meaning


def test_backspace_inside_an_english_token_keeps_the_rest(session):
    _, v = run(session, "ji3fv4{BS}")
    assert v.composition == "我fv"


def test_ctrl_z_undoes_backspace_typing_and_choices(session):
    _, v = run(session, "ji3ap7{BS}")
    assert v.composition == "我"
    _, v = run(session, "{C-z}")
    assert v.composition == "我們"
    _, v = run(session, "{C-y}")
    assert v.composition == "我"
    session._reset_buffer()
    # typing is undone a word (completed syllable) at a time
    _, v = run(session, "ji3ap7{C-z}")
    assert v.composition == "我"
    _, v = run(session, "{C-z}")
    assert v.composition == ""
    session._reset_buffer()
    # a candidate choice is one step
    _, v = run(session, "ji3a87")
    assert v.composition == "我嗎"
    _, v = run(session, "{LEFT}{UP}2")
    assert v.composition == "我嘛"
    _, v = run(session, "{C-z}")
    assert v.composition == "我嗎"


def test_ctrl_z_is_ours_only_while_composing(session):
    from smartime.devtools.simulate import press
    from smartime.engine.keys import KeyInput

    ctrl_z = KeyInput(vk=ord("Z"), ctrl=True)
    handled, _ = press(session, ctrl_z)
    assert handled is False  # nothing composing: the app's own undo
    run(session, "ji3")
    handled, v = press(session, ctrl_z)
    assert handled is True and v.composition == "" and v.commit == ""


def test_undo_in_correction_mode_shares_the_history(session):
    _, v = run(session, "ji3ap7{ESC}x")
    assert v.composition == "我" and v.correcting
    _, v = run(session, "u")
    assert v.composition == "我們" and v.correcting
    _, v = run(session, "{C-z}")  # Ctrl+Z works there too (and stays in correction mode)
    assert v.composition == "我" and v.correcting
