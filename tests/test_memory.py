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
