"""Voice input service: hold the right Ctrl key, speak, release — the text
is typed where the cursor is, in any application.

    python -m smartime.voice.service        (started by the IME when enabled)

* Recognition is local (Breeze-ASR-25 on an NVIDIA GPU, or SenseVoice on
  the CPU); audio never leaves the computer, and the microphone is open only
  while the key is held.
* Right Ctrl + another key is a normal shortcut: recording is cancelled.
* My dictionary's own words (friends, project terms) are passed as hints.
* One instance per user; exits when voice input is turned off in Settings.
"""

from __future__ import annotations

import gc
import logging
import logging.handlers
import queue
import sys
import threading
import time

from .. import paths
from ..config import Config
from . import asr, text, win

log = logging.getLogger("smartime.voice")
MIN_SECONDS = 0.35  # shorter = an accidental tap
MAX_SECONDS = 120
RESULT = win.WM_APP + 10
STATUS = win.WM_APP + 11
HIDE = win.WM_APP + 12
RELOAD = "reload"  # worker job: load the engine chosen in Settings


class Recorder:
    def __init__(self) -> None:
        self.stream = None
        self.chunks: list = []
        self.started = 0.0

    def start(self) -> None:
        import sounddevice as sd

        try:
            sd.query_devices(kind="input")
        except Exception:  # noqa: BLE001 - PortAudioError: no default input device
            raise RuntimeError("找不到麥克風。請接上麥克風，或到 Windows 設定 > 系統 > 音效 選擇輸入裝置") from None
        self.chunks = []
        self.started = time.monotonic()
        self.stream = sd.InputStream(samplerate=asr.SAMPLE_RATE, channels=1, dtype="float32",
                                     callback=lambda data, frames, t, status: self.chunks.append(data.copy()))
        self.stream.start()

    def stop(self):
        import numpy as np

        if self.stream is None:
            return None, 0.0
        self.stream.stop()
        self.stream.close()
        self.stream = None
        seconds = time.monotonic() - self.started
        if not self.chunks:
            return None, seconds
        return np.concatenate(self.chunks)[:, 0], seconds


class VoiceService:
    def __init__(self, recorder=None, accept_injected: bool = False) -> None:
        self.config_path = paths.config_path()
        self.config = Config.load(self.config_path)
        self.engine = None
        self.engine_error = ""
        self.jobs: queue.Queue = queue.Queue()
        self.results: queue.Queue = queue.Queue()
        self.recorder = recorder or Recorder()
        self.recording = False
        self.msg = win.MessageWindow({
            win.PushToTalkHook.PRESS: lambda w, l: self.on_press(),
            win.PushToTalkHook.RELEASE: lambda w, l: self.on_release(),
            win.PushToTalkHook.CANCEL: lambda w, l: self.on_cancel(),
            RESULT: lambda w, l: self.on_result(),
            STATUS: lambda w, l: self.on_status(),
            HIDE: lambda w, l: self.indicator.hide(),
            win.WM_TIMER: lambda w, l: self.on_timer(),
        })
        self.indicator = win.Indicator()
        self.hook = win.PushToTalkHook(self.msg, accept_injected)
        self.status_text = ""
        win.user32.SetTimer(self.msg.hwnd, 1, 3000, None)
        threading.Thread(target=self.worker, daemon=True).start()

    # ------------------------------------------------------------ worker thread
    def load_engine(self) -> None:
        self.engine = None  # drop the old model first (GPU memory)
        gc.collect()
        self.engine_error = ""
        try:
            t0 = time.perf_counter()
            self.engine = asr.create(self.config.voice_engine)
            log.info("engine %s ready in %.1fs", self.engine.name, time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001
            self.engine_error = str(e)
            log.exception("cannot load the speech engine")

    def worker(self) -> None:
        self.load_engine()
        while True:
            audio = self.jobs.get()
            if audio is None:
                return
            if isinstance(audio, str) and audio == RELOAD:
                self.load_engine()
                continue
            if self.engine is None:
                self.results.put(("error", self.engine_error or "語音模型無法載入"))
                self.msg.post(RESULT)
                continue
            try:
                t0 = time.perf_counter()
                mine = self._my_words()
                hot = " ".join(mine) if self.config.voice_hotwords else ""
                raw = self.engine.transcribe(audio, hot)
                out = text.clean(raw, traditional=self.config.voice_traditional, known=mine)
                log.info("recognized %.1fs of audio in %.2fs (%d chars)",
                         len(audio) / asr.SAMPLE_RATE, time.perf_counter() - t0, len(out))
                self.results.put(("text", out))
            except Exception as e:  # noqa: BLE001
                log.exception("recognition failed")
                self.results.put(("error", f"辨識失敗：{e}"))
            self.msg.post(RESULT)

    def _my_words(self) -> list[str]:
        try:
            from ..engine.userdict import UserDict

            user = UserDict(paths.user_db_path())
            try:
                return text.my_words(user)
            finally:
                user.close()
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------ main thread
    def on_press(self) -> None:
        if self.recording:
            return
        try:
            self.recorder.start()
        except RuntimeError as e:  # no microphone: a plain message, no traceback
            log.warning("%s", e)
            self.flash(str(e), seconds=5)
            return
        except Exception as e:  # noqa: BLE001
            log.exception("cannot open the microphone")
            self.flash(f"無法開啟麥克風：{e}")
            return
        self.recording = True
        name = self.engine.name if self.engine else "模型載入中"
        self.indicator.show(f"● 錄音中（{name}）… 放開右 Ctrl 結束")

    def on_cancel(self) -> None:
        if self.recording:
            self.recorder.stop()
            self.recording = False
        self.indicator.hide()

    def on_release(self) -> None:
        if not self.recording:
            return
        self.recording = False
        audio, seconds = self.recorder.stop()
        if audio is None or seconds < MIN_SECONDS:
            self.indicator.hide()
            return
        audio = audio[: int(MAX_SECONDS * asr.SAMPLE_RATE)]
        self.indicator.show("… 辨識中")
        self.jobs.put(audio)

    def on_result(self) -> None:
        kind, value = self.results.get()
        if kind == "text" and value:
            self.indicator.hide()
            win.type_text(value)
        elif kind == "text":
            self.flash("沒有聽到內容")
        else:
            self.flash(value)

    def on_status(self) -> None:
        self.indicator.show(self.status_text)

    def flash(self, message: str, seconds: float = 2.5) -> None:
        self.indicator.show(message)
        threading.Timer(seconds, lambda: self.msg.post(HIDE)).start()

    def on_timer(self) -> None:
        """Every few seconds: follow settings changes; exit when turned off."""
        cfg = Config.load(self.config_path)
        if not cfg.voice_enabled:
            log.info("voice input turned off; exiting")
            self.hook.close()
            self.jobs.put(None)
            win.quit_message_loop()
            return
        changed = cfg.voice_engine != self.config.voice_engine
        self.config = cfg
        if changed:
            log.info("engine changed to %s; reloading", cfg.voice_engine)
            self.jobs.put(RELOAD)


def _setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(
        paths.log_dir() / "voice.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main() -> int:
    _setup_logging()
    if not win.single_instance("Local\\SmartIME.Voice"):
        log.info("already running")
        return 0
    log.info("voice service starting")
    VoiceService()
    win.run_message_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
