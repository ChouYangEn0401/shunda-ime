"""Problems reported with 華碩智慧輸入法 (Phase 0 research, section 0.2).

Phase 3 reproduced the classic strict behaviour (these were xfail);
Phase 4 part 1 (re-ordering + number/English calibration) fixed them, so
they are now regression tests.
"""

from smartime.devtools.simulate import run


def test_swapped_order_still_means_wo(session):
    # ㄛㄨˇ typed instead of ㄨㄛˇ
    _, v = run(session, "ij3")
    assert v.composition == "我"


def test_ei_alone_is_zhuyin_not_letter_o(session):
    # "o" + space should give the symbol ㄟ in a Chinese context, not "o "
    _, v = run(session, "ji3o ")
    assert v.composition == "我ㄟ"


def test_swapped_order_gong_hao(session):
    # ㄥㄍˋㄏㄠˇ -> 更好 (no stray "/", nothing silently eaten)
    _, v = run(session, "/e4cl3")
    assert v.composition == "更好"


def test_mvp_stays_english_in_chinese_context(session):
    # With re-ordering, "mvp" also reads as ㄒㄩㄣ (勳); the curated term
    # prior must keep it English.
    _, v = run(session, "ji3ap7rup4m/4mvp ")
    assert "mvp" in v.composition

