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
