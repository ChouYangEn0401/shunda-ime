"""My dictionary and learned memory: storage, ranking, forgetting, sharing
with the settings app, and the session's learning behaviour."""

from pathlib import Path

import pytest

from smartime import paths
from smartime.config import Config
from smartime.devtools.simulate import run
from smartime.engine.decoder import Decoder
from smartime.engine.layouts import DACHEN
from smartime.engine.lexicon import Lexicon
from smartime.engine.session import Engine, Session
from smartime.engine.userdict import UserDict, boost


@pytest.fixture
def user(tmp_path):
    u = UserDict(tmp_path / "user.db")
    yield u
    u.close()


@pytest.fixture
def mem_engine(user):
    lex = Lexicon(paths.system_db_path(), user)
    yield Engine(lexicon=lex, layout=DACHEN, decoder=Decoder(lex, DACHEN), config=Config())
    lex.close()


@pytest.fixture
def mem_session(mem_engine):
    return Session(mem_engine)


# ------------------------------------------------------------- storage
def test_default_categories(user):
    names = [c["name"] for c in user.categories()]
    # 人工加入 leads: it is where Ctrl+D puts a word before it is sorted,
    # so 常用詞 can be a category the user assigns rather than the bucket
    assert names[:5] == ["人工加入", "常用詞", "朋友", "專案術語", "常用英文"]


def test_learn_counts_and_boost(user):
    user.learn("逗號", "ㄉㄡˋ-ㄏㄠˋ")
    user.learn("逗號", "ㄉㄡˋ-ㄏㄠˋ")
    e = user.lookup("逗號", "ㄉㄡˋ-ㄏㄠˋ")
    assert e.count == 2 and e.source == "learned"
    assert boost(1) < boost(2) < boost(100) <= 3.0


def test_manual_entry_ranks_like_a_common_word(user):
    user.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")
    e = user.lookup("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ")
    assert e.category == "朋友" and e.source == "manual"
    assert e.score(None) == -3.0


def test_forget_learned_then_block(user):
    user.learn("鬥號", "ㄉㄡˋ-ㄏㄠˋ")
    assert user.forget("鬥號", "ㄉㄡˋ-ㄏㄠˋ") == "forgot"
    assert user.lookup("鬥號", "ㄉㄡˋ-ㄏㄠˋ") is None
    assert user.forget("鬥號", "ㄉㄡˋ-ㄏㄠˋ") == "blocked"
    assert user.is_blocked("鬥號", "ㄉㄡˋ-ㄏㄠˋ")
    assert user.stats()["blocked"] == 1


def test_delete_on_a_learned_non_word_marks_the_pairing_wrong(mem_session, user):
    # The user's dictionary had 開新 from an old correction rule; 開心 came
    # out 開新 every time and there was no way to say "these two are wrong".
    user.learn("開新", "ㄎㄞ-ㄒㄧㄣ", origin="fix")
    user.learn("開新", "ㄎㄞ-ㄒㄧㄣ", origin="fix")
    mem_session.engine.lexicon.invalidate()
    _, v = run(mem_session, "d9 vup ")
    assert v.composition == "開新"
    _, v = run(mem_session, "{DOWN}")
    assert v.candidates[0] == "開新"
    _, v = run(mem_session, "{DEL}")
    assert v.composition == "開心"
    assert "不是詞" in v.notice
    assert user.is_blocked("開新", "ㄎㄞ-ㄒㄧㄣ")
    # a later correction cannot teach it back
    user.learn("開新", "ㄎㄞ-ㄒㄧㄣ", origin="fix")
    assert user.is_blocked("開新", "ㄎㄞ-ㄒㄧㄣ")
    s = Session(mem_session.engine)  # start over: 開 and 新 pair with their other neighbours
    _, v = run(s, "cp3d9 vup ")
    assert v.composition == "很開心"


def test_delete_on_a_learned_real_word_only_forgets_it(mem_session, user):
    # 新的 is a word: Delete takes back the learning, it does not ban the word
    user.learn("新的", "ㄒㄧㄣ-ㄉㄜ˙", origin="fix")
    mem_session.engine.lexicon.invalidate()
    run(mem_session, "vup 2k7{DOWN}")
    _, v = run(mem_session, "{DEL}")
    assert "已忘記" in v.notice
    assert not user.is_blocked("新的", "ㄒㄧㄣ-ㄉㄜ˙")


def test_tidy_drops_invented_correction_pairs(user, mem_engine):
    user.learn("開新", "ㄎㄞ-ㄒㄧㄣ", origin="fix")  # not a word: dropped
    user.learn("新的", "ㄒㄧㄣ-ㄉㄜ˙", origin="fix")  # a word: kept
    user.learn("跟屎", "ㄍㄣ-ㄕˇ", origin="fix")
    user.update(next(e["id"] for e in user.list() if e["phrase"] == "跟屎"), category="常用詞")  # sorted: kept
    user.learn("很心", "ㄏㄣˇ-ㄒㄧㄣ", origin="pick")  # not from a fix: kept
    gone = user.forget_invented_pairs(mem_engine.lexicon.in_system)
    assert gone == ["開新"]
    assert {e["phrase"] for e in user.list()} == {"新的", "跟屎", "很心"}


def test_forget_never_deletes_my_own_entry(user):
    user.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")
    assert user.forget("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ") == "manual"
    assert user.lookup("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ") is not None


def test_changes_from_another_process_are_seen(user, tmp_path):
    # the settings app opens the same file with its own connection
    other = UserDict(tmp_path / "user.db")
    other.add("林志豪", "ㄌㄧㄣˊ-ㄓˋ-ㄏㄠˊ", "zh", "朋友")
    other.close()
    assert user.lookup("林志豪", "ㄌㄧㄣˊ-ㄓˋ-ㄏㄠˊ") is None  # not yet
    assert user.refresh() is True
    assert user.lookup("林志豪", "ㄌㄧㄣˊ-ㄓˋ-ㄏㄠˊ") is not None


def test_export_and_merge_into_another_pc(user, tmp_path):
    user.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")
    user.learn("逗號", "ㄉㄡˋ-ㄏㄠˋ")
    user.block("鬥號", "ㄉㄡˋ-ㄏㄠˋ")
    backup = tmp_path / "backup.db"
    user.backup_to(backup)

    other = UserDict(tmp_path / "other" / "user.db")
    other.learn("逗號", "ㄉㄡˋ-ㄏㄠˋ")
    report = other.merge_from(backup)
    assert (report["words"], report["updated"]) == (2, 1)  # 陳怡君 + 鬥號 new, 逗號 already here
    assert other.lookup("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ").category == "朋友"
    assert other.lookup("逗號", "ㄉㄡˋ-ㄏㄠˋ").count == 2  # summed
    assert other.is_blocked("鬥號", "ㄉㄡˋ-ㄏㄠˋ")
    other.close()


def test_several_machines_merge_into_one_dictionary(tmp_path):
    """The point of import: a folder of exports from different machines,
    poured into one dictionary in any order, ends up holding all of it —
    nothing replaced, counts added up (reported as a wish: 「把多份匯出檔
    （相當於不同工作環境的資訊）最終合在一起」)."""
    def export(name, build) -> Path:
        d = tmp_path / name
        u = UserDict(d / "user.db")
        build(u)
        snap = d / "snap.db"
        u.backup_to(snap, stamp=True)
        u.close()
        return snap

    def work(u):
        u.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "工作")
        for _ in range(3):
            u.learn("會議", "ㄏㄨㄟˋ-ㄧˋ")
        u.add_snippet("公司地址 100 號", "公司", "addr")
        u.add_custom_symbols("★")
        u.block("鬥號", "ㄉㄡˋ-ㄏㄠˋ")

    def home(u):
        for _ in range(5):
            u.learn("會議", "ㄏㄨㄟˋ-ㄧˋ")  # the same word, used on the other machine
        u.add("家裡電話", "ㄐㄧㄚ-ㄌㄧˇ-ㄉㄧㄢˋ-ㄏㄨㄚˋ", "zh", "家裡")
        u.add_snippet("公司地址 100 號", "公司", "addr")  # byte-identical to work's
        u.add_custom_symbols("♥")

    laptop, desktop = export("work", work), export("home", home)
    mine = UserDict(tmp_path / "mine" / "user.db")
    mine.merge_from(laptop)
    mine.merge_from(desktop)

    assert mine.lookup("會議", "ㄏㄨㄟˋ-ㄧˋ").count == 8  # 3 + 5
    assert mine.lookup("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ").category == "工作"
    assert mine.lookup("家裡電話", "ㄐㄧㄚ-ㄌㄧˇ-ㄉㄧㄢˋ-ㄏㄨㄚˋ").category == "家裡"
    assert mine.is_blocked("鬥號", "ㄉㄡˋ-ㄏㄠˋ")
    assert [s["body"] for s in mine.snippets()] == ["公司地址 100 號", ]  # the duplicate is not doubled
    assert mine.custom_symbols() == ["★", "♥"]
    assert {"工作", "家裡"} <= {c["name"] for c in mine.categories()}
    mine.close()


def test_importing_the_same_file_again_does_not_inflate_the_counts(tmp_path):
    """Found while checking the above: the merge adds counts, so dropping
    the same export in twice (easy with a folder of them) silently doubled
    every usage count it carried and skewed the ranking. The stamped
    export_id makes the repeat settle instead of pile up."""
    source = UserDict(tmp_path / "src" / "user.db")
    for _ in range(4):
        source.learn("會議", "ㄏㄨㄟˋ-ㄧˋ")
    snap = tmp_path / "snap.db"
    source.backup_to(snap, stamp=True)
    source.close()

    mine = UserDict(tmp_path / "mine" / "user.db")
    assert mine.merge_from(snap)["repeat"] is False
    assert mine.lookup("會議", "ㄏㄨㄟˋ-ㄧˋ").count == 4
    assert mine.merge_from(snap)["repeat"] is True
    assert mine.lookup("會議", "ㄏㄨㄟˋ-ㄧˋ").count == 4, "the same file twice is not 8"

    # a *new* export from that machine still brings what it has learned since
    source = UserDict(tmp_path / "src" / "user.db")
    for _ in range(2):
        source.learn("會議", "ㄏㄨㄟˋ-ㄧˋ")
    later = tmp_path / "later.db"
    source.backup_to(later, stamp=True)
    source.close()
    assert mine.merge_from(later)["repeat"] is False
    assert mine.lookup("會議", "ㄏㄨㄟˋ-ㄧˋ").count == 10  # 4 + the new file's 6
    mine.close()


def test_a_repeat_import_still_restores_anything_deleted_locally(tmp_path):
    """A repeat is not a no-op: it is still the way back if something was
    deleted here by mistake. Only the counts settle."""
    source = UserDict(tmp_path / "src" / "user.db")
    source.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")
    source.add_custom_symbols("★")
    snap = tmp_path / "snap.db"
    source.backup_to(snap, stamp=True)
    source.close()

    mine = UserDict(tmp_path / "mine" / "user.db")
    mine.merge_from(snap)
    mine.delete(mine.lookup("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ").id)
    mine.remove_custom_symbol("★")

    report = mine.merge_from(snap)
    assert report["repeat"] is True
    assert mine.lookup("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ") is not None
    assert mine.custom_symbols() == ["★"]
    mine.close()


# ------------------------------------------------------------- ranking in the decoder
def test_learned_choice_wins_next_time(mem_session):
    # 打逗號 decodes as 打鬥號 (unigram tie); pick 逗號 once ...
    _, v = run(mem_session, "2832.4cl4")
    assert v.composition == "打鬥號"
    run(mem_session, "{DOWN}")
    labels = mem_session.view().candidates
    run(mem_session, str(labels.index("逗號") + 1) + "{ENTER}")
    # ... and the next time it is the default
    _, v = run(mem_session, "2832.4cl4")
    assert v.composition == "打逗號"


def test_blocked_phrase_is_never_suggested(mem_session):
    # 打鬥號 = 打鬥 + 號; open candidates at the first character
    run(mem_session, "2832.4cl4{HOME}{DOWN}")
    items = [c.text for c in mem_session.cand.items]
    assert "打鬥" in items
    mem_session.cand.index = items.index("打鬥")  # highlight it, then Delete
    _, v = run(mem_session, "{DEL}")
    assert v.notice == "不再建議「打鬥」（可在設定頁還原）"
    assert "打鬥" not in [c.text for c in mem_session.cand.items]
    run(mem_session, "{ESC}")  # close the list
    # the same keys now read without the blocked word, here and next time
    assert mem_session.view().composition == "打逗號"
    _, v = run(Session(mem_session.engine), "2832.4cl4")
    assert v.composition == "打逗號"


def test_ctrl_d_adds_the_typed_name_with_a_category_note(mem_session):
    # type a name whose characters the lexicon would not pick, fix it ...
    run(mem_session, "t06u6rmp ")  # ㄔㄣˊㄧˊㄐㄩㄣ
    _, v = run(mem_session, "{C-d}")
    added = v.composition
    assert v.notice == f"已加入詞庫：{added}（人工加入）"
    run(mem_session, "{ENTER}")
    # ... next time it comes out whole, with its category in the window
    _, v = run(mem_session, "t06u6rmp ")
    assert v.composition == added
    _, v = run(mem_session, "{DOWN}")
    assert v.candidate_notes[0] == "人工加入"


def test_ctrl_d_adds_an_english_word_as_typed(mem_session, user):
    """「英文版本的 Ctrl+D 也要可以用」: the word before the cursor, exactly as
    typed — the IME's own changes to it (a dropped last letter, a one-slip
    correction) are what the user is overruling."""
    _, v = run(mem_session, "venv ")
    assert v.composition == "ven "  # the stray-key drop ate the last letter
    _, v = run(mem_session, "{C-d}")
    assert v.notice == "已加入詞庫：venv（常用英文）"
    assert v.composition == "venv "  # read again with the word known: whole
    assert user.en["venv"].category == "常用英文"
    run(mem_session, "{ENTER}")
    # next time it comes out whole without help, also next to Chinese
    _, v = run(Session(mem_session.engine), "venv ")
    assert v.composition == "venv "
    _, v = run(Session(mem_session.engine), "ji3venv ")
    assert v.composition == "我venv "


def test_ctrl_d_keeps_a_dropped_first_letter_and_undoes_an_autocorrect(mem_session, user):
    _, v = run(mem_session, "pnpm ")
    assert v.composition == "npm "
    _, v = run(mem_session, "{C-d}")
    assert v.composition == "pnpm " and "pnpm" in user.en
    run(mem_session, "{ENTER}")
    _, v = run(mem_session, "wrold ")
    assert v.composition == "world "  # 英文打錯自動更正
    _, v = run(mem_session, "{C-d}")
    assert v.composition == "wrold " and "wrold" in user.en  # "no, I mean it"
    run(mem_session, "{ENTER}")
    _, v = run(Session(mem_session.engine), "wrold ")
    assert v.composition == "wrold "  # a word of mine is never corrected


def test_ctrl_d_keeps_an_identifier_with_an_underscore(mem_session, user):
    """「打了 _ 以後 ctrl+D 他就會說游標前面沒有可以加入的文字」: m_ and
    m_index are one word, and once added they come out whole."""
    _, v = run(mem_session, "m_")
    assert v.composition == "_"  # the lone m is dropped as a slip
    _, v = run(mem_session, "{C-d}")
    assert v.notice == "已加入詞庫：m_（常用英文）" and "m_" in user.en
    assert v.composition == "m_"
    run(mem_session, "{ENTER}")
    _, v = run(Session(mem_session.engine), "m_count")
    assert v.composition == "m_count"  # the prefix keeps its m from now on
    _, v = run(Session(mem_session.engine), "ji3m_index{C-d}")
    assert "m_index" in user.en
    _, v = run(Session(mem_session.engine), "ji3m_index ji3")
    assert v.composition == "我m_index 我"


def test_ctrl_d_before_chinese_ignores_a_trailing_stray_key(mem_session, user):
    # a single letter after a sentence is dropped as a slip; Ctrl+D still
    # means the Chinese before it, not the letter
    run(mem_session, "ji3ap7 ")
    _, v = run(mem_session, "{C-d}")
    assert v.notice == "已加入詞庫：我們（人工加入）"
    assert not user.en


def test_add_word_in_correction_mode_takes_the_english_word_under_the_cursor(mem_session, user):
    _, v = run(mem_session, "ji3venv {ESC}")
    assert v.composition == "我ven " and v.correcting
    _, v = run(mem_session, "a")  # the cursor stops on the word: a adds it, as typed
    assert v.composition == "我venv " and v.correcting and "venv" in user.en
    # Ctrl+D does the same there and stays in correction mode
    _, v = run(mem_session, "{LEFT}{C-d}")
    assert v.notice == "已加入詞庫：我（人工加入）" and v.correcting


def test_tab_continuation_is_learned(mem_session, user):
    _, v = run(mem_session, "ao6u.3")
    accepted = v.composition + v.suggestion
    run(mem_session, "{TAB}")
    assert user.lookup(accepted, mem_session.decoding.segments[-1].readings and "-".join(
        mem_session.decoding.segments[-1].readings)) is not None


def test_learning_can_be_turned_off(mem_session, user):
    mem_session.cfg.learn = False
    run(mem_session, "2832.4cl4{DOWN}2")
    assert user.stats()["learned"] == 0


def test_engine_reloads_config_when_the_file_changes(tmp_path, lexicon, decoder):
    import os
    import time

    cfg_path = tmp_path / "config.json"
    Config().save(cfg_path)
    engine = Engine(lexicon=lexicon, layout=DACHEN, decoder=decoder, config=Config.load(cfg_path),
                    config_path=cfg_path)
    engine.refresh()
    changed = Config()
    changed.halfwidth_symbols = '"<'
    changed.save(cfg_path)
    later = time.time() + 5
    os.utime(cfg_path, (later, later))
    engine.refresh()
    assert engine.config.halfwidth_symbols == '"<'
    assert "<" in decoder.halfwidth_symbols
    decoder.halfwidth_symbols = frozenset('"')  # restore the shared fixture


def test_first_learning_is_announced_once(tmp_path, monkeypatch):
    # reported: new users can't tell that the IME learns, or how to undo it
    from smartime.devtools.simulate import run
    from smartime.engine.session import Session
    from smartime.pime.server import build_engine

    monkeypatch.setenv("SMARTIME_USER_DIR", str(tmp_path))
    session = Session(build_engine())
    _, v = run(session, "ji3ap7{DOWN}")
    _, v = run(session, str(v.candidates.index("們") + 1))
    assert "記住了「們」" in v.notice and "Delete" in v.notice

    _, v = run(session, "{ENTER}ji3ap7{DOWN}")
    assert "學過" in v.candidate_notes
    assert "Delete" in v.candidate_title  # how to undo, right where it matters
    _, v = run(session, str(v.candidates.index("們") + 1))
    assert v.notice == ""  # announced only the first time


def test_tidy_forgets_old_one_off_picks_only(tmp_path):
    import time

    from smartime.engine.userdict import UserDict

    u = UserDict(tmp_path / "user.db")
    u.learn("逗號", "ㄉㄡˋ-ㄏㄠˋ")  # one old pick: forgotten
    u.learn("們", "ㄇㄣ˙")
    u.learn("們", "ㄇㄣ˙")  # used twice: kept
    u.learn("今天", "ㄐㄧㄣ-ㄊㄧㄢ")  # one recent pick: kept
    u.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")  # mine: kept
    old = time.time() - 200 * 86400
    u._con.execute("UPDATE entries SET last_used=?, created=? WHERE phrase IN ('逗號', '們', '陳怡君')", (old, old))
    assert u.tidy(compact=True) == 1
    left = {e["phrase"] for e in u.list()}
    assert left == {"們", "今天", "陳怡君"}
    assert u.stats()["bytes"] > 0
    u.close()


# ------------------------------------------------------------- corrections become words (#2)
def test_a_corrected_character_is_remembered_with_its_neighbour(mem_session, user):
    # 打逗號 comes out as 打鬥號 (homophones, word frequency only)
    _, v = run(mem_session, "2832.4cl4")
    assert v.composition == "打鬥號"
    _, v = run(mem_session, "{LEFT}{LEFT}{DOWN}4")  # pick 逗 alone
    assert v.composition == "打逗號"
    learned = {(r["phrase"], r["origin"]) for r in user.list(source="learned")}
    # the real word around the fix, not the lone character (which would
    # then be preferred everywhere and cause new mistakes)
    assert learned == {("逗號", "fix")}
    assert "（修正）" in v.notice
    mem_session._reset_buffer()
    _, v = run(mem_session, "2832.4cl4")
    assert v.composition == "打逗號"


def test_smart_suggest_also_remembers_the_three_characters_around_a_fix(mem_session, user):
    """Asked for: 「把 OOX 修正以後只記了 OO 和 OX」 — a pair makes the same
    sentence decode right, but is too short to come back as a continuation.
    Behind the experimental 超智慧推薦 switch, the run around the fix is
    remembered as a phrase too."""
    mem_session.cfg.smart_suggest = True
    try:
        _, v = run(mem_session, "2832.4cl4{LEFT}{LEFT}{DOWN}4")  # 打鬥號 -> 打逗號
        assert v.composition == "打逗號"
        learned = {(r["phrase"], r["origin"]) for r in user.list(source="learned")}
        assert learned == {("逗號", "fix"), ("打逗號", "fix")}
        assert any(p == "打逗號" for p, _, _ in mem_session.engine.lexicon.completions("打逗"))
    finally:
        mem_session.cfg.smart_suggest = False


def test_the_three_character_run_goes_again_if_the_sentence_moves_on(mem_session, user):
    """Learned with the same provisional "fix" origin as the pairs, so a
    later fix that leaves it out of the final sentence takes it back."""
    mem_session.cfg.smart_suggest = True
    try:
        run(mem_session, "2832.4cl4{LEFT}{LEFT}{DOWN}4")  # 打逗號
        final, _ = run(mem_session, "{ESC}{HOME}j{ENTER}")  # then fix the sentence again
        assert "打逗號" not in final
        assert "打逗號" not in learned_phrases(user)
    finally:
        mem_session.cfg.smart_suggest = False


def test_an_accepted_continuation_comes_first_next_time(mem_engine, user):
    """Asked: 「接受 recommendation 的建議以後，要不要讓那些詞變成高頻詞」.
    It already does — every way of taking one (Tab, Ctrl+digit, the
    Shift+Tab list) goes through _accept_suggestion, which learns it — but
    nothing pinned that down until now."""
    _, v = run(Session(mem_engine), "ao6u.3")  # 沒有 …
    fourth = v.suggestions[3]
    run(Session(mem_engine), "ao6u.3{S-TAB}4{ENTER}")
    assert (fourth, "tab") in {(r["phrase"][2:], r["origin"]) for r in user.list(source="learned")}
    _, v = run(Session(mem_engine), "ao6u.3")
    assert v.suggestions[0] == fourth, f"{fourth} should lead now: {v.suggestions}"


def test_picking_a_whole_word_is_remembered_as_it_is(mem_session, user):
    run(mem_session, "2832.4cl4{LEFT}{LEFT}{DOWN}1")  # 逗號 as one candidate
    assert {(r["phrase"], r["origin"]) for r in user.list(source="learned")} == {("逗號", "pick")}


def test_a_lone_character_is_remembered_alone(mem_session, user):
    run(mem_session, "2.4{DOWN}")
    cand = mem_session.cand
    other = next(i for i, c in enumerate(cand.page_items()) if c.text != "鬥" and len(c.text) == 1)
    run(mem_session, str(other + 1))
    rows = user.list(source="learned")
    assert len(rows) == 1 and len(rows[0]["phrase"]) == 1 and rows[0]["origin"] == "pick"


def test_schema_1_database_gets_the_origin_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        "INSERT INTO meta VALUES ('schema', '1');"
        "CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, sort INTEGER NOT NULL DEFAULT 0);"
        "CREATE TABLE entries (id INTEGER PRIMARY KEY, phrase TEXT NOT NULL, reading TEXT NOT NULL DEFAULT '',"
        " kind TEXT NOT NULL DEFAULT 'zh', category_id INTEGER, source TEXT NOT NULL DEFAULT 'learned',"
        " count INTEGER NOT NULL DEFAULT 0, last_used REAL, created REAL NOT NULL,"
        " blocked INTEGER NOT NULL DEFAULT 0, UNIQUE (phrase, reading));"
        "INSERT INTO entries (phrase, reading, count, created) VALUES ('我們', 'ㄨㄛˇ-ㄇㄣ˙', 2, 1);")
    con.commit()
    con.close()
    u = UserDict(path)
    rows = u.list()
    assert rows[0]["phrase"] == "我們" and rows[0]["origin"] == ""
    u.learn("好", "ㄏㄠˇ", origin="fix")
    assert {r["phrase"]: r["origin"] for r in u.list()}["好"] == "fix"
    u.close()


def test_inbox_and_my_words_views_sort_and_page(user):
    import time as _time

    user.learn("甲", "ㄐㄧㄚˇ")
    _time.sleep(0.01)
    user.learn("乙", "ㄧˇ")
    user.learn("乙", "ㄧˇ")
    user.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")
    inbox = [r["phrase"] for r in user.list(view="inbox", sort="recent")]
    assert inbox == ["乙", "甲"]  # most recent first (default on the settings page)
    assert [r["phrase"] for r in user.list(view="inbox", sort="count")] == ["乙", "甲"]
    assert [r["phrase"] for r in user.list(view="mine")] == ["陳怡君"]
    assert user.count(view="inbox") == 2 and user.count(view="mine") == 1
    assert [r["phrase"] for r in user.list(view="inbox", sort="recent", limit=1, offset=1)] == ["甲"]
    # giving an inbox entry a category moves it to my words
    entry_id = user.list(view="inbox")[0]["id"]
    user.update(entry_id, category="常用詞")
    assert user.count(view="inbox") == 1 and user.count(view="mine") == 2


def learned_phrases(user):
    return {e.phrase for e in user._entries() if e.source == "learned"}


def test_fixing_several_characters_does_not_leave_the_words_in_between(mem_session, user):
    """Reported: 「當我選字的時候，他會亂把東西加入常用字…我打四個字，然後一個
    一個改字，你可以去看一下他都亂改了什麼」.

    A correction is remembered with its neighbour, so the same sentence
    comes out right next time. Fixing character after character therefore
    built a pair around every character on its way out: the real dictionary
    had 彩但 beside 彩蛋 and 蛋模 beside nothing at all. Once the sentence is
    settled, the pairs it does not contain go again.
    """
    run(mem_session, "5p 284 ")  # two characters, both likely wrong
    first = mem_session.view().composition
    run(mem_session, "{ESC}{HOME}j")  # change the first one
    run(mem_session, "lj")  # and then the second one
    final = mem_session.view().composition
    assert final != first
    run(mem_session, "{ENTER}")

    for phrase in learned_phrases(user):
        assert phrase in final, f"「{phrase}」 is not in 「{final}」 and should not have been kept"


def test_a_pair_that_survives_to_the_end_is_kept(mem_session, user):
    run(mem_session, "5p 284 ")
    final, _ = run(mem_session, "{ESC}{HOME}j{ENTER}")
    kept = learned_phrases(user)
    assert kept, "the correction itself must still be remembered"
    assert all(p in final for p in kept)


# ------------------------------------------------------------- 我的符號 (custom symbols)
def test_custom_symbols_paste_one_per_line(user):
    """Kaomoji that contain their own internal spaces — "( ͡° ͜ʖ ͡°)" — rule
    out splitting a paste on whitespace too; one line is one symbol."""
    n = user.add_custom_symbols("( ͡° ͜ʖ ͡°)\n★\n\n☆")
    assert n == 3
    assert user.custom_symbols() == ["( ͡° ͜ʖ ͡°)", "★", "☆"]


def test_custom_symbols_paste_is_additive_and_deduplicates(user):
    user.add_custom_symbols("★\n☆")
    n = user.add_custom_symbols("★\n♥")  # ★ already there
    assert n == 1
    assert user.custom_symbols() == ["★", "☆", "♥"]


def test_custom_symbols_reject_an_improbable_single_line(user):
    # someone pasted a whole blob with no newlines: not one symbol
    n = user.add_custom_symbols("x" * 50)
    assert n == 0
    assert user.custom_symbols() == []


def test_remove_custom_symbol(user):
    user.add_custom_symbols("★\n☆")
    assert user.remove_custom_symbol("★") is True
    assert user.remove_custom_symbol("★") is False  # already gone
    assert user.custom_symbols() == ["☆"]


def test_custom_symbols_are_merged_additively_on_import(user, tmp_path):
    user.add_custom_symbols("★\n☆")
    backup = tmp_path / "backup.db"
    user.backup_to(backup)

    other = UserDict(tmp_path / "other" / "user.db")
    other.add_custom_symbols("☆\n♥")  # ☆ already there, from a different PC
    other.merge_from(backup)
    assert sorted(other.custom_symbols()) == sorted(["★", "☆", "♥"])
    other.close()


# ------------------------------------------------------------- learning must not break decoding
def test_learned_single_characters_do_not_change_what_the_decoder_picks(mem_engine, user):
    """Reported: 「原本的選字反而又被你改壞了」. In the user's own dictionary
    常, 示, 舊 and 指 had been learned as lone characters, and at a word's
    boost each one won every sentence: 嘗試 came out 常示, 就 became 舊, 只
    became 指. A lone character carries no context, so it no longer moves
    the decoder — it still leads the candidate window (學過)."""
    for ch, reading in (("常", "ㄔㄤˊ"), ("示", "ㄕˋ"), ("舊", "ㄐㄧㄡˋ"), ("指", "ㄓˇ")):
        for _ in range(4):
            user.learn(ch, reading, "zh", "pick")
    mem_engine.lexicon.invalidate()
    _, v = run(Session(mem_engine), "2; ji3rup wu0 t;6g4283")
    assert v.composition == "當我今天嘗試打"
    _, v = run(Session(mem_engine), "ru.4cjo4")  # 就會
    assert v.composition == "就會"
    _, v = run(Session(mem_engine), "53g4")  # 只是
    assert v.composition.startswith("只")

    s = Session(mem_engine)
    run(s, "53{DOWN}")
    first = s.cand.shown[0]
    assert (first.text, first.group) == ("指", "學過"), "still first in the candidate window"


def test_a_correction_without_a_real_word_beside_it_is_remembered_as_three_characters(mem_session, user):
    """228 of the 242 correction pairs in the user's dictionary were not
    words (跟屎, 寄刀, 的視…): when neither neighbour made a word, both pairs
    were learned, and each leaked into every sentence with those sounds (的是
    came out 的視). The three characters together only match their own
    sentence, so that is what is remembered now."""
    _, v = run(mem_session, "ji3cp3dj94")  # 我很快
    assert v.composition == "我很快"
    _, v = run(mem_session, "{LEFT}{LEFT}{DOWN}3")  # a homophone of 很 in the middle
    fixed = v.composition
    assert fixed != "我很快" and len(fixed) == 3
    learned = {r["phrase"] for r in user.list(source="learned")}
    assert learned == {fixed}, f"only the run, no invented pairs: {learned}"
    mem_session._reset_buffer()
    _, v = run(mem_session, "ji3cp3dj94")
    assert v.composition == fixed, "and the same sentence still comes out the corrected way"


def test_j_in_correction_mode_goes_to_the_most_likely_other_character(mem_engine, user):
    """Reported: 「每次打出來我看結果都是錯的」. With 嘛 learned the candidate
    list reads 嘛 嗎 蟆 … (學過 first) while 嗎 is on screen; j walked on from
    嗎's position and typed 蟆, skipping the obvious 嘛."""
    for _ in range(3):
        user.learn("嘛", "ㄇㄚ˙", "zh", "pick")
    mem_engine.lexicon.invalidate()
    s = Session(mem_engine)
    _, v = run(s, "ji3a87")
    assert v.composition == "我嗎"
    _, v = run(s, "{ESC}j")
    assert v.composition == "我嘛"
    _, v = run(s, "k")
    assert v.composition == "我嗎", "k comes straight back"


def test_a_word_i_added_beats_a_common_homophone(user, mem_session):
    """Reported: 「我都加入常用了，打字的時候還是出現別的…同一個打法有兩種」.
    An added word started at -3.0, so a very common homophone (台灣 -2.79)
    still won over 臺灣 added by hand. A multi-character word in 我的詞庫
    now ranks first among words with its reading."""
    run(mem_session, "w96j0 ")
    assert mem_session.view().composition == "台灣"
    mem_session.reset()
    user.add("臺灣", "ㄊㄞˊ-ㄨㄢ", category="常用詞")
    mem_session.engine.lexicon.invalidate()
    run(mem_session, "w96j0 ")
    assert mem_session.view().composition == "臺灣"
    assert mem_session.engine.lexicon.phrases("ㄊㄞˊ-ㄨㄢ")[0][0] == "臺灣"


def test_a_fix_that_needed_its_neighbour_is_learned_with_it(user, mem_session):
    """Reported: 每一週 → 每一洲; picking 一週 learned only 一週, so the next
    每一週 still came out 美一週 (每 alone loses to 美). The neighbour that
    had to be held is learned with the choice: next time it is right."""
    run(mem_session, "ao3u 5. {DOWN}1")  # 1. 一週
    assert mem_session.view().composition == "每一週"
    run(mem_session, "{ENTER}")
    assert user.lookup("每一週", "ㄇㄟˇ-ㄧ-ㄓㄡ") is not None
    _, v = run(mem_session, "ao3u 5. ")
    assert v.composition == "每一週"


def test_the_same_correction_twice_becomes_my_word(user, mem_engine):
    """修正紀錄: every correction is counted (X -> Y, how); made twice, the
    result goes into 我的詞庫 under 程式推薦, where the user can see it."""
    for _ in range(2):
        s = Session(mem_engine)
        _, v = run(s, "ao3u 5. {ESC}")
        assert v.composition == "每一洲"
        run(s, "{DOWN}3{ENTER}")  # correction mode: 洲 -> 週 (3rd candidate)
        # learning that did not stick (tidied, or outweighed): the next time
        # the same sentence comes out wrong again and is fixed again
        user.clear_learned()
        mem_engine.lexicon.invalidate()
    rows = user.corrections()
    assert rows and rows[0]["right"].endswith("週") and rows[0]["count"] >= 2
    promoted = [r for r in user.list(limit=100) if r["category"] == "程式推薦"]
    assert promoted and promoted[0]["phrase"] == rows[0]["right"]
    assert rows[0]["promoted"]


def test_keeping_a_skipped_key_is_counted_and_twice_becomes_my_word(user, mem_engine):
    """#5: 「你自己幫我省略但使用者又嘗試加回來的」 — recorded. The second time
    the same key is brought back, the word goes into 我的詞庫 (程式推薦), and
    a word there is never cut short again."""
    for _ in range(2):
        s = Session(mem_engine)
        run(s, "ji3ee/4dj94{ESC}vv{HOME}llle{ENTER}")  # keep the second e
    rows = user.corrections()
    assert rows and rows[0]["methods"] == ["keep"] and rows[0]["count"] == 2
    # a lone letter between Chinese is not a word: counted, never promoted
    assert rows[0]["right"] == "e" and not rows[0]["promoted"]


def test_moving_a_boundary_by_hand_is_counted_once(user, mem_engine):
    s = Session(mem_engine)
    run(s, "su3z03102845j04xk78 {ESC}hhh{S-LEFT}{S-LEFT}{S-LEFT}{S-LEFT}l{ENTER}")
    rows = user.corrections()
    assert len(rows) == 1 and rows[0]["methods"] == ["regroup"] and rows[0]["count"] == 1
    assert "10" in rows[0]["right"] and "大" in rows[0]["right"]


def test_cleanup_suggestions_rules(tmp_path):
    """整理建議: only the 自動收集 area; once (not a word, 14+ days), idle
    (90+ days), English slips; sorted by reason, then oldest first."""
    import time

    from smartime.engine.userdict import UserDict

    u = UserDict(tmp_path / "user.db")
    now = time.time()
    words = {"候選", "今天", "the"}

    def is_word(phrase, reading, kind):
        return phrase in words

    def fix(word):
        return {"teh": "the"}.get(word)

    def learn(phrase, reading="", kind="zh", n=1, days=0):
        for _ in range(n):
            u.learn(phrase, reading, kind)
        t = now - days * 86400
        u._con.execute("UPDATE entries SET last_used=?, created=? WHERE phrase=?", (t, t, phrase))

    learn("開新", "ㄎㄞ-ㄒㄧㄣ", days=20)  # once, not a word, 20 days: once
    learn("跟屎", "ㄍㄣ-ㄕˇ", days=40)  # once, older: once, listed first
    learn("的視", "ㄉㄜ˙-ㄕˋ", days=5)  # once but recent: not yet
    learn("候選", "ㄏㄡˋ-ㄒㄩㄢˇ", days=30)  # once but a word: kept
    learn("今天", "ㄐㄧㄣ-ㄊㄧㄢ", n=5, days=100)  # used often, long ago: idle
    learn("teh", kind="en", n=3)  # a slip: typo, however recent
    learn("ok", kind="en", n=1, days=1)
    u.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")  # mine: never suggested
    u._con.execute("UPDATE entries SET last_used=?, created=? WHERE phrase='陳怡君'", (now - 400 * 86400,) * 2)
    learn("開會", "ㄎㄞ-ㄏㄨㄟˋ", days=200)
    u.update(u.lookup("開會", "ㄎㄞ-ㄏㄨㄟˋ").id, category="常用詞")  # sorted: never suggested
    u.block("鬥號", "ㄉㄡˋ-ㄏㄠˋ")
    u._load()

    out = u.cleanup_suggestions(is_word, fix, now=now)
    got = [(r["phrase"], r["reason"]) for r in out["rows"]]
    assert got == [("跟屎", "once"), ("開新", "once"), ("今天", "idle"), ("teh", "typo")]
    assert out["total"] == 4
    assert out["rows"][-1]["fix"] == "the" and out["rows"][-1]["label"] == "英文像打錯"
    assert out["rows"][0]["label"] == "只用過一次" and out["rows"][2]["label"] == "很久沒用"
    capped = u.cleanup_suggestions(is_word, fix, limit=2, now=now)
    assert len(capped["rows"]) == 2 and capped["total"] == 4

    # bulk delete: one transaction, the words are gone from lookups too
    ids = [r["id"] for r in out["rows"][:2]]
    assert u.delete_many(ids) == 2
    assert u.lookup("開新", "ㄎㄞ-ㄒㄧㄣ") is None and u.lookup("跟屎", "ㄍㄣ-ㄕˇ") is None
    assert [r["phrase"] for r in u.cleanup_suggestions(is_word, fix, now=now)["rows"]] == ["今天", "teh"]
    u.close()
