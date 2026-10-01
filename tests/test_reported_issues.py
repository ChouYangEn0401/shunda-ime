"""Problems reported with 華碩智慧輸入法 (Phase 0 research, section 0.2).

Phase 3 deliberately reproduces the classic strict behaviour, so these are
expected failures. Phase 4 (noisy-channel decoder) must turn them green —
remove the xfail markers there.
"""

import pytest

from smartime.devtools.simulate import run

PHASE4 = pytest.mark.xfail(reason="fixed in Phase 4 (noisy-channel decoder)", strict=True)


@PHASE4
def test_swapped_order_still_means_wo(session):
    # ㄛㄨˇ typed instead of ㄨㄛˇ
    _, v = run(session, "ij3")
    assert v.composition == "我"


@PHASE4
def test_ei_alone_is_zhuyin_not_letter_o(session):
    # "o" + space should give the symbol ㄟ in a Chinese context, not "o "
    _, v = run(session, "ji3o ")
    assert v.composition == "我ㄟ"


@PHASE4
def test_swapped_order_gong_hao(session):
    # ㄥㄍˋㄏㄠˇ -> 更好 (no stray "/", nothing silently eaten)
    _, v = run(session, "/e4cl3")
    assert v.composition == "更好"


def test_mvp_stays_english_in_chinese_context(session):
    # Passes in Phase 3 only because ㄩㄒㄣ is out of order. Once Phase 4
    # accepts re-ordered syllables, "mvp" also reads as ㄒㄩㄣ (勳), so this
    # becomes a regression guard for the English/term prior.
    _, v = run(session, "ji3ap7rup4m/4mvp ")
    assert "mvp" in v.composition
