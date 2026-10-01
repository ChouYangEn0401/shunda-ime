"""Voice input: the parts that do not need a microphone or a GPU."""

import pytest

from smartime.engine.userdict import UserDict
from smartime.voice import models, text


def test_hotwords_are_my_own_words(tmp_path):
    u = UserDict(tmp_path / "user.db")
    u.add("陳怡君", "ㄔㄣˊ-ㄧˊ-ㄐㄩㄣ", "zh", "朋友")
    u.add("vscode", "", "en", "常用英文")
    u.learn("逗號", "ㄉㄡˋ-ㄏㄠˋ")  # learned, not mine: not a hint
    hot = text.hotwords_from_dictionary(u)
    assert "陳怡君" in hot and "vscode" in hot and "逗號" not in hot
    u.close()


def test_model_status_and_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SMARTIME_MODELS_DIR", str(tmp_path))
    st = models.status()
    assert set(st) == {"breeze", "sensevoice"}
    assert not st["breeze"]["installed"]
    (tmp_path / "breeze-asr-25-ct2").mkdir()
    (tmp_path / "breeze-asr-25-ct2" / "model.bin").write_bytes(b"x")
    assert models.installed("breeze")


def test_clean_joins_chinese_and_converts_to_traditional():
    pytest.importorskip("opencc")
    assert text.clean("我 今天 要 开 会") == "我今天要開會"
    assert text.clean("然后 我 去 剪 头发") == "然後我去剪頭髮"
    # characters only: the words someone said stay (s2twp would give 檔案)
    assert text.clean("把 API 文件寄给他") == "把 API 文件寄給他"


def test_sensevoice_capitals_and_split_acronyms():
    # real SenseVoice output for a mixed sentence
    raw = "我今天下午要開一個 MEETING 討論這個 MV P 的 DEADLINE 記得把 API 文件寄給陳怡君"
    assert text.fix_english(raw) == "我今天下午要開一個 meeting 討論這個 MVP 的 deadline 記得把 API 文件寄給陳怡君"
    assert text.fix_english("THE TRIBAL CHIEF CALLED FOR THE BOY") == "The tribal chief called for the boy"
    assert text.fix_english("I'M OK WITH THAT") == "I'm OK with that"


def test_mixed_case_output_is_left_alone_but_my_spelling_wins():
    breeze = "我今天要開一個 meeting 討論這個 MVP 的 deadline"
    assert text.fix_english(breeze) == breeze
    assert text.fix_english("我在用 vscode 寫 code", known=["VSCode", "陳怡君"]) == "我在用 VSCode 寫 code"
    assert text.fix_english("用 V S CODE 開", known=["VSCode"]) == "用 VSCode 開"


def test_engine_choice_without_models(tmp_path, monkeypatch):
    from smartime.voice import asr

    monkeypatch.setenv("SMARTIME_MODELS_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="還沒有下載語音模型"):
        asr.create("auto")


def test_gpu_without_cuda_libraries_uses_the_cpu(monkeypatch):
    # an NVIDIA card but no cuBLAS/cuDNN (GPU packages not installed): the
    # model would load and then fail at the first recognition
    ctranslate2 = pytest.importorskip("ctranslate2")
    from smartime.voice import asr

    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)

    def missing(name):
        raise OSError(f"{name} not found")

    monkeypatch.setattr(asr.ctypes, "WinDLL", missing)
    assert not asr.cuda_available()
