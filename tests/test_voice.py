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


class _Target:
    def __init__(self):
        self.posted = []

    def post(self, msg, wparam=0, lparam=0):
        self.posted.append(msg)


def test_push_to_talk_hook_press_release_and_shortcut():
    from smartime.voice import win

    target = _Target()
    hook = win.PushToTalkHook(target, start=False)  # no real hook in tests
    P, R, C = win.PushToTalkHook.PRESS, win.PushToTalkHook.RELEASE, win.PushToTalkHook.CANCEL
    hook.on_key(win.VK_RCONTROL, True)
    first = hook.last_down
    hook.on_key(win.VK_RCONTROL, True)  # auto-repeat while held: no second press
    assert target.posted == [P] and hook.last_down >= first
    hook.on_key(win.VK_RCONTROL, False)
    assert target.posted == [P, R]
    target.posted.clear()
    hook.on_key(win.VK_RCONTROL, True)
    hook.on_key(0x41, True)  # right Ctrl + A: a shortcut
    hook.on_key(win.VK_RCONTROL, False)
    assert target.posted == [P, C, C]


def test_release_counts_as_missed_only_when_both_signals_agree():
    from smartime.voice.service import REPEAT_GAP, release_missed

    assert not release_missed(physically_down=True, since_last_down=60)  # no auto-repeat (FilterKeys)
    assert not release_missed(physically_down=False, since_last_down=0.1)  # GetAsyncKeyState blocked
    assert release_missed(physically_down=False, since_last_down=REPEAT_GAP + 1)


class _Stream:
    def __init__(self, fail=False):
        self.fail, self.closed, self.aborted = fail, False, False

    def stop(self):
        if self.fail:
            raise RuntimeError("device went away")

    def abort(self):
        self.aborted = True
        self.stop()

    def close(self):
        self.closed = True


def test_recorder_closes_the_stream_even_when_stopping_fails():
    from smartime.voice.service import Recorder

    rec = Recorder()
    rec.stream = s = _Stream(fail=True)
    with pytest.raises(RuntimeError):
        rec.stop()
    assert s.closed and rec.stream is None
    rec.stream = s = _Stream()
    rec.chunks = ["audio"]
    rec.cancel()
    assert s.aborted and s.closed and rec.stream is None and rec.chunks == []


class _Recorder:
    def __init__(self, seconds=5.0):
        self.cancelled = self.stopped = self.started = 0
        self.seconds = seconds

    def start(self):
        self.started += 1

    def stop(self):
        import numpy as np

        self.stopped += 1
        return np.zeros(int(self.seconds * 16000), dtype=np.float32), self.seconds

    def cancel(self):
        self.cancelled += 1


class _Hook:
    def __init__(self):
        self.down, self.combo, self.last_down, self.reinstalled = False, False, 0.0, 0

    def reset(self):
        self.down = self.combo = False

    def reinstall(self):
        self.reinstalled += 1


class _Indicator:
    def __init__(self):
        self.hidden = 0
        self.text = ""

    def show(self, text):
        self.text = text

    def hide(self):
        self.hidden += 1


def _service(tmp_path, monkeypatch, *, held=False, foreground=7):
    """A VoiceService without its window, hook, microphone or model."""
    import queue
    import time
    import types

    from smartime.config import Config
    from smartime.voice import service, win

    monkeypatch.setattr(win.user32, "SetTimer", lambda *a: 1)
    monkeypatch.setattr(win.user32, "KillTimer", lambda *a: 1)
    monkeypatch.setattr(win.user32, "GetForegroundWindow", lambda: foreground)
    monkeypatch.setattr(win, "key_down", lambda vk: held)
    s = object.__new__(service.VoiceService)
    s.posted = []
    s.msg = types.SimpleNamespace(hwnd=None, post=lambda *a: s.posted.append(a))
    s.recorder, s.hook, s.indicator = _Recorder(), _Hook(), _Indicator()
    s.recording, s.recording_since, s.hook_suspect, s.mic = False, 0.0, 0, "mic"
    s.press_window, s.press_error, s.locked, s.pending_notice, s.shown = 7, "", False, "", 0
    s.engine, s.engine_error, s.unloaded, s.reload_queued = None, "", False, False
    s.last_used = time.monotonic()
    s.jobs, s.results = queue.Queue(), queue.Queue()
    s.flashed = []
    s.flash = lambda message, seconds=2.5: s.flashed.append(message)
    cfg = Config()
    cfg.voice_enabled = True
    s.config_path = tmp_path / "config.json"
    cfg.save(s.config_path)
    s.config = cfg
    return s


def test_sleep_and_lock_keep_what_was_said_for_the_clipboard(tmp_path, monkeypatch):
    from smartime.voice import service, win

    s = _service(tmp_path, monkeypatch)
    for event in (lambda: s.on_power(win.PBT_APMSUSPEND), lambda: s.on_session(win.WTS_SESSION_LOCK)):
        s.recording, s.hook.down = True, True
        event()
        assert not s.recording and not s.hook.down  # microphone closed, press forgotten
        audio, delivery = s.jobs.get_nowait()
        assert len(audio) and delivery == service.CLIPBOARD  # recognized, not thrown away
    assert s.recorder.cancelled == 0
    s.on_power(win.PBT_APMRESUMEAUTOMATIC)
    s.on_session(win.WTS_SESSION_UNLOCK)
    assert s.hook.reinstalled == 2  # Windows may have dropped the hook meanwhile


def test_a_release_the_hook_missed_still_gives_the_text(tmp_path, monkeypatch):
    import time

    from smartime.voice import service

    s = _service(tmp_path, monkeypatch, held=False)
    s.recording, s.hook.down, s.hook.last_down = True, True, time.monotonic() - 60
    s.check_keys()
    assert not s.recording and not s.hook.down and s.hook.reinstalled == 1
    assert s.recorder.cancelled == 0 and s.jobs.get_nowait()[1] == service.SAME_WINDOW


def _deliver(s, monkeypatch, delivery, clipboard_ok=True):
    from smartime.voice import win

    typed, clip = [], []
    monkeypatch.setattr(win, "type_text", typed.append)
    monkeypatch.setattr(win, "set_clipboard", lambda hwnd, t: clip.append(t) or clipboard_ok)
    s.results.put(("text", "今天開會", delivery))
    s.on_result()
    return typed, clip


def test_the_text_goes_where_the_user_dictated_or_to_the_clipboard(tmp_path, monkeypatch):
    from smartime.voice import service

    s = _service(tmp_path, monkeypatch, foreground=7)  # the same window as at the press
    assert _deliver(s, monkeypatch, service.SAME_WINDOW) == (["今天開會"], [])
    s = _service(tmp_path, monkeypatch, foreground=99)  # the focus moved on meanwhile
    assert _deliver(s, monkeypatch, service.SAME_WINDOW) == ([], ["今天開會"])
    assert "剪貼簿" in s.flashed[0]
    s = _service(tmp_path, monkeypatch, foreground=7)  # after sleep: never typed
    assert _deliver(s, monkeypatch, service.CLIPBOARD) == ([], ["今天開會"])
    s = _service(tmp_path, monkeypatch, foreground=99)  # clipboard busy: typing beats losing it
    assert _deliver(s, monkeypatch, service.CLIPBOARD, clipboard_ok=False) == (["今天開會"], ["今天開會"])


def test_a_notice_waits_for_the_screen_to_be_unlocked(tmp_path, monkeypatch):
    from smartime.voice import service, win

    s = _service(tmp_path, monkeypatch)
    s.locked = True
    _deliver(s, monkeypatch, service.CLIPBOARD)
    assert not s.flashed and s.pending_notice
    s.on_session(win.WTS_SESSION_UNLOCK)
    assert "剪貼簿" in s.flashed[0] and not s.pending_notice


def test_a_long_dictation_is_not_cut_at_two_minutes(tmp_path, monkeypatch):
    s = _service(tmp_path, monkeypatch)
    s.recorder = _Recorder(seconds=600)
    s.recording = True
    s.on_release()
    audio, _ = s.jobs.get_nowait()
    assert len(audio) == 600 * 16000  # it used to keep only the first 120 s, without a word


def test_an_old_flash_does_not_hide_a_newer_message(tmp_path, monkeypatch):
    from smartime.voice import service

    import types

    monkeypatch.setattr(service.threading, "Timer", lambda *a: types.SimpleNamespace(start=lambda: None))
    s = _service(tmp_path, monkeypatch)
    service.VoiceService.flash(s, "沒有聽到內容")  # its timer will hide it later...
    old = s.shown
    s.recording, s.recording_since = True, 0.0
    s.on_tick()  # ...but recording has started again meanwhile
    s.hide_if(old)
    assert s.indicator.hidden == 0 and "錄音中" in s.indicator.text
    s.hide_if(s.shown)
    assert s.indicator.hidden == 1


def test_an_idle_model_is_released_and_loaded_again_while_talking(tmp_path, monkeypatch):
    import time

    from smartime.voice import service

    s = _service(tmp_path, monkeypatch)
    s.engine = object()
    s.maybe_unload()
    assert s.engine is not None  # off by default
    s.config.voice_unload_minutes = 10
    s.last_used = time.monotonic() - 11 * 60
    s.maybe_unload()
    assert s.engine is None and s.unloaded
    s.on_press()
    s.on_press()  # (already recording: nothing more)
    assert s.jobs.get_nowait() == service.RELOAD and s.jobs.empty()  # loading starts at the press

    class Engine:
        def transcribe(self, audio, hot):
            return "好"

    s.reload_queued, loads = False, []
    s.load_engine = lambda: (loads.append(1), setattr(s, "engine", Engine()), setattr(s, "unloaded", False))
    s.engine, s.unloaded = None, True  # released again before the reload ran
    s._my_words = lambda: []
    s.recognize([0.0] * 16000, service.TYPE)
    assert loads == [1] and s.results.get_nowait() == ("text", "好", service.TYPE)


def test_long_audio_is_cut_at_the_pauses():
    import numpy as np

    from smartime.voice import asr

    rng = np.random.default_rng(0)
    sec = asr.SAMPLE_RATE
    speech = lambda s: rng.normal(0, 0.3, int(s * sec)).astype(np.float32)  # noqa: E731
    silence = lambda s: np.zeros(int(s * sec), dtype=np.float32)  # noqa: E731
    audio = np.concatenate([speech(22), silence(0.5), speech(21), silence(0.5), speech(10)])
    pieces = asr.split_at_pauses(audio)
    assert np.array_equal(np.concatenate(pieces), audio)  # nothing lost or doubled
    assert all(len(p) <= 25 * sec for p in pieces)
    assert abs(len(pieces[0]) - 22.25 * sec) < 0.3 * sec  # cut inside the pause


def test_someone_still_talking_is_never_cut_off(tmp_path, monkeypatch):
    import time

    s = _service(tmp_path, monkeypatch, held=False)  # GetAsyncKeyState says up...
    s.recording, s.hook.down, s.hook.last_down = True, True, time.monotonic()  # ...but it auto-repeats
    s.check_keys()
    assert s.recording and not s.recorder.cancelled
    s = _service(tmp_path, monkeypatch, held=True)  # held, and no auto-repeat at all
    s.recording, s.hook.down, s.hook.last_down = True, True, time.monotonic() - 600
    s.check_keys()
    assert s.recording and not s.recorder.cancelled


def test_a_hook_that_sees_nothing_is_installed_again(tmp_path, monkeypatch):
    s = _service(tmp_path, monkeypatch, held=True)  # right Ctrl held, the hook saw no press
    s.check_keys()
    assert s.hook.reinstalled == 0  # one tick could be a press between two checks
    s.check_keys()
    assert s.hook.reinstalled == 1


def test_devices_are_read_again_only_when_something_changed(tmp_path, monkeypatch):
    from smartime.voice import service, win

    calls = []
    monkeypatch.setattr(service, "microphone", lambda refresh=False: calls.append(refresh) or "mic")
    s = _service(tmp_path, monkeypatch)
    for _ in range(50):  # two and a half minutes of idle timer ticks
        s.on_timer(service.TIMER_CONFIG)
    assert calls == []  # each re-read leaks inside PortAudio
    s.on_device_change(win.DBT_DEVNODES_CHANGED)
    s.on_timer(service.TIMER_DEVICES)
    assert calls == [True]
    s.recording = True
    s.on_timer(service.TIMER_DEVICES)  # never while recording
    assert calls == [True]


def test_a_failing_gpu_model_is_loaded_again_once(tmp_path, monkeypatch):
    s = _service(tmp_path, monkeypatch)

    class Broken:
        def transcribe(self, audio, hot):
            raise RuntimeError("CUDA failed with error unspecified launch failure")

    class Fresh:
        def transcribe(self, audio, hot):
            return "你好"

    s.engine = Broken()
    loads = []

    def load_engine():
        loads.append(1)
        s.engine = Fresh()

    s.load_engine = load_engine
    assert s._transcribe([0.0], "") == "你好" and loads == [1]


def test_indicator_sits_on_the_monitor_in_use():
    from smartime.voice import win

    # a second monitor to the right of a 1920-wide primary, taskbar 40 px
    assert win.bottom_center((1920, 0, 3840, 1040), 460, 46) == (1920 + 730, 1040 - 46 - 40)


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
