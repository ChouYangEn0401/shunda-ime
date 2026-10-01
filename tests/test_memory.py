"""My dictionary and learned memory: storage, ranking, forgetting, sharing
with the settings app, and the session's learning behaviour."""

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
    assert names[:4] == ["常用詞", "朋友", "專案術語", "常用英文"]


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
    assert other.merge_from(backup) == 3
    assert other.lookup("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ").category == "朋友"
    assert other.lookup("逗號", "ㄉㄡˋ-ㄏㄠˋ").count == 2  # summed
    assert other.is_blocked("鬥號", "ㄉㄡˋ-ㄏㄠˋ")
    other.close()


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
    run(mem_session, "{ESC}{ESC}")
    _, v = run(mem_session, "2832.4cl4")
    assert v.composition == "打逗號"


def test_ctrl_d_adds_the_typed_name_with_a_category_note(mem_session):
    # type a name whose characters the lexicon would not pick, fix it ...
    run(mem_session, "t06u6rmp ")  # ㄔㄣˊㄧˊㄐㄩㄣ
    _, v = run(mem_session, "{C-d}")
    added = v.composition
    assert v.notice == f"已加入詞庫：{added}（常用詞）"
    run(mem_session, "{ENTER}")
    # ... next time it comes out whole, with its category in the window
    _, v = run(mem_session, "t06u6rmp ")
    assert v.composition == added
    _, v = run(mem_session, "{DOWN}")
    assert v.candidate_notes[0] == "常用詞"


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
