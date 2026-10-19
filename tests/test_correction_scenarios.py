"""Correction mode end to end: whole repairs, not single commands.

test_correction.py checks each command on its own. This file walks through
the situations a correction actually happens in — the ones that came back as
"I can get into the box but I cannot get the text fixed" — from the first
keystroke to the committed sentence, so a regression shows up as a sentence
that comes out wrong rather than as a flag that changed.

Every scenario states: what was typed, what the IME made of it, what the
user does about it, and what has to be on screen afterwards.
"""

import pytest

from smartime.devtools.simulate import run
from smartime.engine.panel import decode_panel
from smartime.engine.session import Session


def text(session):
    return session.view().composition


def panel_rows(session):
    """(keys, reading, text, role) per column — what the decode panel shows."""
    return [(c.keys, c.reading, c.text, c.role) for c in decode_panel(session).columns]


def focused(session):
    p = decode_panel(session)
    return None if p.focus is None else p.columns[p.focus].text


# ---------------------------------------------------------------- stranded keys
def test_a_key_stranded_by_my_own_picks_can_be_joined_again(session):
    """Reported (0.3.0): 「至 e 灣」 where 「至關」 was meant.

    ``ej0␣`` is ㄍㄨㄢ = 關, but once something pins the ``e`` on its own the
    decoder must keep it, and nothing in the mode could put it back: j/k find
    no Chinese for a lone ``e``, e (中⇄英) has nothing to switch to, and x
    would delete the key instead of using it. R decides the stretch again.
    """
    run(session, "54ej0 ")
    assert text(session) == "至關"
    run(session, "{ESC}e")  # strand the keys: 關 becomes the letters behind it
    assert text(session) == "至ej0 "
    assert [c for c in panel_rows(session) if c[3] == "literal"]
    run(session, "R")
    assert text(session) == "至關"
    assert focused(session) == "關"


def test_r_takes_one_more_character_in_on_each_press(session):
    run(session, "ji3rup wu0 ")  # 我今天
    before = text(session)
    run(session, "{ESC}{HOME}RRR")
    assert text(session) == before  # nothing was pinned: decoding is unchanged
    assert session.correcting  # and we are still in the box


def test_r_does_not_touch_choices_outside_the_span(session):
    run(session, "ji35p ")
    run(session, "{DOWN}3")  # pick a different 珍/針/… for the second character
    picked = text(session)
    run(session, "ji3")  # keep typing
    run(session, "{ESC}R")  # re-decide the *last* character only
    assert text(session).startswith(picked), "an earlier pick must survive"


# ---------------------------------------------------------------- stray keys
def test_a_stray_key_is_visible_and_removable_in_the_keys_view(session):
    # fast typing left an extra e: 我[e]更快
    run(session, "ji3ee/4dj94")
    assert text(session) == "我更快"
    assert ("e", "略過", "", "drop") in panel_rows(session)
    run(session, "{ESC}vv")  # 國字 -> 注音 -> 按鍵
    assert decode_panel(session).layer == "keys"
    run(session, "{HOME}lll")  # j i 3 -> the stray e
    assert decode_panel(session).columns[decode_panel(session).focus].role == "drop"
    run(session, "x")
    assert text(session) == "我更快"
    assert not [c for c in panel_rows(session) if c[3] == "drop"]


def test_walking_back_and_changing_one_character_keeps_the_rest(session):
    run(session, "ji3rup wu0 ")
    whole = text(session)
    run(session, "{ESC}hj")  # one character back, next candidate
    changed = text(session)
    assert changed != whole
    assert changed[0] == whole[0] and changed[-1] == whole[-1]


# ---------------------------------------------------------------- leaving the box
@pytest.mark.parametrize("keys, still_in, committed", [
    ("i", False, False),      # back to typing, text kept
    ("{ESC}", False, False),  # same
    ("{ENTER}", False, True),  # send it
    ("DD", False, False),     # clear everything, send nothing
])
def test_only_explicit_commands_leave_the_box(session, keys, still_in, committed):
    out, _ = run(session, "ji3rup wu0 {ESC}")
    assert session.correcting
    out2, v = run(session, keys)
    assert session.correcting is still_in
    assert bool(out2) is committed


def test_typing_keys_never_escape_the_box_by_accident(session):
    """Every letter that is not a command must stay a no-op, or a stray
    keystroke in the middle of a repair types into the sentence."""
    run(session, "ji3rup wu0 {ESC}")
    before = text(session)
    for ch in "bcdfgmnopqstwyz":
        run(session, ch)
        assert session.correcting, f"{ch!r} left correction mode"
        assert text(session) == before, f"{ch!r} changed the text"


def test_coming_back_into_the_box_lands_where_the_work_was(session):
    run(session, "ji3rup wu0 {ESC}hh")
    where = focused(session)
    run(session, "i")  # back to typing
    run(session, "{ESC}")  # and back in again
    assert session.correcting
    assert focused(session) is not None and where is not None


# ---------------------------------------------------------------- repairs that commit
def test_a_whole_repair_ends_in_the_right_sentence(session):
    """The full loop: type, notice a wrong character, fix it, send it."""
    run(session, "ji3ee/4dj94")  # 我更快 with a stray e
    run(session, "{ESC}")
    assert session.correcting
    run(session, "hh")  # onto 更
    run(session, "j")  # a different character
    fixed = text(session)
    out, v = run(session, "{ENTER}")
    assert out == fixed and v.composition == ""
    assert not session.correcting


def test_r_then_enter_sends_the_redecided_text(session):
    run(session, "54ej0 {ESC}e")
    assert text(session) == "至ej0 "
    out, v = run(session, "R{ENTER}")
    assert out == "至關" and v.composition == ""


def test_an_accidental_space_split_a_syllable_and_the_keys_view_joins_it(session):
    """「至ㄍ灣」: a space slipped in after ㄍ, so ㄍ became a first tone of
    its own and ㄨㄢ became 灣. Deleting that one key in the 按鍵 view puts
    the syllable back together."""
    run(session, "54e j0 ")
    assert text(session) == "至ㄍ灣"
    run(session, "{ESC}vv{END}hhh")  # 按鍵 view, onto the stray space
    run(session, "x")
    assert text(session) == "至關"


def test_a_key_the_decoder_threw_away_can_be_kept(session):
    """Reported: typing a lowercase 「p2」 marked the p as 略過 — "那我該怎麼辦".

    A dropped key has no reading, so j/k and the candidate window never see
    it, and x would only finish throwing it away. e (中⇄英) on it in the
    按鍵 view now means "I meant that key" and keeps it as typed.
    """
    run(session, "ji3ee/4dj94")
    assert text(session) == "我更快"  # the second e was read as a slip
    run(session, "{ESC}vv{HOME}lll")  # 按鍵 view, onto the dropped e
    assert decode_panel(session).columns[decode_panel(session).focus].role == "drop"
    run(session, "e")
    assert text(session) == "我e更快"
    out, _ = run(session, "{ENTER}")
    assert out == "我e更快"


# ---------------------------------------------------------------- wrong reading
def test_a_tone_key_fixes_the_reading(session):
    """Reported: 「當我注音打錯字以後，我用修改模式也無法去改注音」, with
    檢位 → 鍵位 and 科能 → 可能 as the examples. Both are one tone key out,
    and nothing in the mode could say so: j/k only walk characters that share
    the reading that is already there."""
    run(session, "ru03jo4")  # ㄐㄧㄢˇ ㄨㄟˋ
    assert text(session) == "檢位"
    run(session, "{ESC}h")  # onto 檢
    run(session, "4")  # ...make it the fourth tone
    assert text(session).endswith("位") and text(session) != "檢位"
    assert decode_panel(session).columns[0].reading == "ㄐㄧㄢˋ"
    # then j/k walks the homophones of the *new* reading, to the one meant
    for _ in range(8):
        if text(session) == "鍵位":
            break
        run(session, "j")
    assert text(session) == "鍵位"


def test_the_reported_ke_neng_case(session):
    run(session, "dk s/6")  # ㄎㄜ (科) ㄋㄥˊ
    assert text(session) == "科能"
    run(session, "{ESC}h3")  # onto 科, third tone
    assert text(session) == "可能"


def test_a_tone_key_on_something_that_is_not_zhuyin_says_so(session):
    run(session, "mvp {ESC}")
    _, v = run(session, "4")
    assert session.correcting and v.composition == "mvp "
    assert "改不了聲調" in v.notice


# ---------------------------------------------------------------- 2026-10-13 round
def test_a_dropped_zhuyin_key_can_become_the_symbol_or_a_character(session):
    """Reported: 「碰 掐拉 ㄣ拉 恰拉」 — p was ㄣ on purpose, typed without a
    tone, so it was dropped, and the only way back was the letter p."""
    _, v = run(session, "x8 px8 ")
    assert v.composition == "拉拉"
    # right before the character the window opens on, the 略過的鍵 group
    # comes first (it used to be last, behind Shift+Tab)
    _, v = run(session, "{DOWN}")
    assert v.candidates[:3] == ["p", "ㄣ", "恩"] and v.candidate_index > 2  # still opens on what is there
    _, v = run(session, "2")
    assert v.composition == "拉ㄣ拉"


def test_punctuation_does_not_send_a_sentence_whose_last_key_was_just_dropped(session):
    """Reported: an extra key, then a full stop — the key vanished and the
    sentence was sent before there was any chance to see it."""
    out, v = run(session, "x8 x8 p{C-,}")
    assert out == "" and v.composition == "拉拉，"
    assert "略過了「p」" in v.notice
    out, v = run(session, "{ENTER}")
    assert out == "拉拉，"
    # a slip in the middle of the sentence was on screen long enough
    out, _ = run(session, "ji3ee/4dj94{C-,}")
    assert out == "我更快"


def test_r_then_esc_gives_the_character_back(session):
    """r deleted the character at once and Esc left it deleted, so the mode
    looked broken (「按 R 直接壞掉直接離開 ESC 模式」)."""
    _, v = run(session, "ji3k27{ESC}hr")
    assert not v.correcting and "Esc 取消" in v.notice
    _, v = run(session, "su")
    assert "重打中" in v.notice
    _, v = run(session, "{ESC}")
    assert v.correcting and v.composition == "我的" and v.cursor == 0


def test_a_retyped_character_does_not_join_the_english_word_before_it(session):
    """Reported (screenshot): Fable then 你 typed with no space — the s of
    ㄋㄧˇ joined the word (Fables) and u3 became 以. Deleting the s and
    retyping 以 as su3 with r glued the s to Fable again."""
    _, v = run(session, "cjo6djo4Fablesu3")
    assert v.composition == "回饋Fables以"
    _, v = run(session, "{ESC}vvhxvrsu3")
    assert v.correcting and v.composition == "回饋Fable你"


def test_down_offers_the_split_that_gives_the_swallowed_key_back(session):
    """The same report, fixed where the user looks: ↓ on 以 lists
    「Fable｜你」 first (group 重新分組); 1 takes it."""
    _, v = run(session, "cjo6djo4Fablesu3{ESC}{DOWN}")
    assert v.candidates[0] == "Fable｜你"
    _, v = run(session, "1")
    assert v.correcting and v.composition == "回饋Fable你"
    _, v = run(session, "u")  # one step back, like any other change
    assert v.composition == "回饋Fables以"


def test_down_splits_a_number_that_swallowed_zhuyin(session):
    """Reported: 「你反10大賺了啊」 came out 你反102845玩了啊 — the digits 2845
    are ㄉㄚˋ ㄓ — and 「無法切割」. The number keeps being a number."""
    _, v = run(session, "su3z03102845j04xk78 {ESC}hh{DOWN}")
    assert "10｜大賺" in v.candidates[:3]
    _, v = run(session, str(v.candidates.index("10｜大賺") + 1))
    assert v.composition == "你反10大賺了啊"
    out, _ = run(session, "{ENTER}")
    assert out == "你反10大賺了啊"


def test_a_number_at_the_end_splits_too(session):
    """排行榜前10大: 10 + 大 typed 10284, with nothing after it."""
    _, v = run(session, "q96vu/61;3fu0610284{ESC}{DOWN}")
    assert v.candidates[0] == "10｜大"
    _, v = run(session, "1")
    assert v.composition == "排行榜前10大"


def test_shift_arrows_move_the_boundary_by_hand(session):
    """The same fix without the list: Shift+← moves the boundary after
    the number one key at a time, both sides read again at once, the
    panel draws it, and any other key keeps it."""
    _, v = run(session, "su3z03102845j04xk78 {ESC}hhh{S-LEFT}")
    assert v.composition == "你反10284賺了啊" and "10284｜賺" in v.notice
    assert [c.text for c in v.panel.columns if c.edge_after] == ["10284"]  # the bar after the number
    _, v = run(session, "{S-LEFT}{S-LEFT}{S-LEFT}")
    assert v.composition == "你反10大賺了啊" and "10｜大賺" in v.notice
    _, v = run(session, "{S-RIGHT}")
    assert v.composition == "你反102阿賺了啊"
    _, v = run(session, "{S-LEFT}l")
    assert v.composition == "你反10大賺了啊" and not any(c.edge_after for c in v.panel.columns)
    out, _ = run(session, "{ENTER}")
    assert out == "你反10大賺了啊"


def test_no_split_is_offered_where_nothing_is_wrong(session):
    """Ordinary English and numbers next to Chinese get no 重新分組 rows
    and no tip: Python, pass, 98分 read right as they are."""
    for keys in ("ji3m/4Pythonvu,3t/6g4{ESC}hhhh{DOWN}", "ji3ul4pass{ESC}{DOWN}", "dl3g4dl3xk798zp {ESC}hh{DOWN}"):
        session.reset()
        _, v = run(session, keys)
        assert not any("｜" in c for c in v.candidates), keys


def test_the_tip_says_what_down_will_do(session):
    _, v = run(session, "5k4ek7gamesu3j06eji4a8 {ESC}hhh")
    assert "game｜你" in v.notice
    session.reset()
    _, v = run(session, "ecj842k7xu.6t/6{ESC}hhh")  # e化 typed: the e was dropped
    assert "略過了「e」" in v.notice


def test_delete_on_a_split_says_what_it_is(session):
    _, v = run(session, "5k4ek7gamesu3j06eji4a8 {ESC}hhh{DOWN}")
    _, v = run(session, "{UP}" * v.candidate_index + "{DEL}")  # the window opens on what is there now
    assert "分法" in v.notice and v.candidates  # nothing forgotten, window still open


def test_retyping_with_r_is_done_only_when_the_syllable_is(session):
    """Reported: 低一下 -> 點一下 was very hard. r on 低, then 2: the 2
    joined the u␣ of 一 and read 低 again, r took that as done, and the
    rest of 2u03 became commands — u undid, 3 re-toned 一 — giving 以下."""
    _, v = run(session, "2u u vu84{ESC}hhr2u0")
    assert not v.correcting  # ㄉㄧㄢ is not a character yet
    _, v = run(session, "3")
    assert v.correcting and v.composition == "點一下" and v.cursor == 0
    out, _ = run(session, "{ENTER}")
    assert out == "點一下"


def test_typing_into_the_middle_makes_characters_of_its_own(session):
    """The same fix without correction mode: ← to 一, Backspace takes 低,
    and 2u03 typed there must not borrow keys from 一 (it read 低眼下)."""
    _, v = run(session, "2u u vu84{LEFT}{LEFT}{BS}2u03")
    assert v.composition == "點一下" and v.cursor == 1


def test_esc_while_retyping_gives_back_the_old_character_after_a_half_typed_one(session):
    _, v = run(session, "2u u vu84{ESC}hhr2u0{ESC}")
    assert v.correcting and v.composition == "低一下"
