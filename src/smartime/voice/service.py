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
import json
import logging
import os
import logging.handlers
import queue
import sys
import threading
import time

from .. import paths, restart
from ..config import Config
from . import asr, text, win

log = logging.getLogger("smartime.voice")
MIN_SECONDS = 0.35  # shorter = an accidental tap — or a tap that opens the IME's symbol panel
TIMER_CONFIG, TIMER_HELD, TIMER_DEVICES, TIMER_TICK = 1, 2, 3, 4
REPEAT_GAP = 2.0  # a held key auto-repeats several times a second; this long without one = not held
# Where a recording's text goes. Someone who talked must never lose it, and
# it must never be typed into a window they did not dictate into.
TYPE, SAME_WINDOW, CLIPBOARD = "type", "same-window", "clipboard"
CLIPBOARD_NOTICE = "沒收到放開右 Ctrl 的訊號：說的話放在剪貼簿，按 Ctrl+V 貼上"
DEVICE_SETTLE_MS = 2000  # devices come and go in bursts (and late after resume): refresh once it is quiet


def release_missed(physically_down: bool, since_last_down: float) -> bool:
    """While recording: was right Ctrl let go somewhere the hook could not
    see (sleep, lock screen, UAC prompt, a hook Windows removed)? Both
    signals have to say so, so one of them misbehaving (an anti-cheat
    blocking GetAsyncKeyState, auto-repeat turned off) never cuts off
    someone who is still talking."""
    return not physically_down and since_last_down > REPEAT_GAP
RESULT = win.WM_APP + 10
STATUS = win.WM_APP + 11
HIDE = win.WM_APP + 12
RELOAD = "reload"  # worker job: load the engine chosen in Settings
UNLOAD_CHECK_SECONDS = 30


def microphone(refresh: bool = False) -> str:
    """Name of the default input device, "" when there is none. PortAudio
    lists devices once; ``refresh`` re-reads them (a Bluetooth headset
    connected later). Never call it while recording."""
    import sounddevice as sd

    if refresh:
        try:
            sd._terminate()
            sd._initialize()
        except Exception:  # noqa: BLE001
            pass
    try:
        return str(sd.query_devices(kind="input")["name"])
    except Exception:  # noqa: BLE001 - PortAudioError: no default input device
        return ""


def status_path():
    return paths.user_dir() / "voice-status.json"


class Recorder:
    def __init__(self) -> None:
        self.stream = None
        self.chunks: list = []
        self.started = 0.0

    def start(self) -> None:
        import sounddevice as sd

        if not microphone() and not microphone(refresh=True):
            raise RuntimeError("找不到麥克風。請接上麥克風，或到 Windows 設定 > 系統 > 音效 選擇輸入裝置")
        self.chunks = []
        self.started = time.monotonic()
        self.stream = sd.InputStream(samplerate=asr.SAMPLE_RATE, channels=1, dtype="float32",
                                     callback=lambda data, frames, t, status: self.chunks.append(data.copy()))
        self.stream.start()

    def _close(self, abort: bool) -> None:
        """Close the stream even when stopping it fails (a microphone that
        went away during sleep): an unclosed stream keeps the device open."""
        stream, self.stream = self.stream, None
        if stream is None:
            return
        try:
            stream.abort() if abort else stream.stop()
        finally:
            stream.close()

    def stop(self):
        import numpy as np

        if self.stream is None:
            return None, 0.0
        self._close(abort=False)
        seconds = time.monotonic() - self.started
        if not self.chunks:
            return None, seconds
        return np.concatenate(self.chunks)[:, 0], seconds

    def cancel(self) -> None:
        """Stop at once and throw the audio away."""
        self._close(abort=True)
        self.chunks = []


class VoiceService:
    def __init__(self, recorder=None, accept_injected: bool = False) -> None:
        self.config_path = paths.config_path()
        self.config = Config.load(self.config_path)
        self.engine = None
        self.engine_error = ""
        self.unloaded = False  # released after being idle; the next press loads it again
        self.reload_queued = False
        self.last_used = time.monotonic()
        self.jobs: queue.Queue = queue.Queue()
        self.results: queue.Queue = queue.Queue()
        self.recorder = recorder or Recorder()
        self.recording = False
        self.recording_since = 0.0
        self.press_window = None  # the window that had the focus when right Ctrl went down
        self.press_error = ""  # microphone problem, shown only if the key is really held
        self.hook_suspect = 0  # timer ticks in a row with right Ctrl held but unseen by the hook
        self.locked = False
        self.pending_notice = ""  # to show once the session is unlocked
        self.shown = 0  # counts what the indicator showed; a late hide only hides its own message
        self.mic = microphone()
        self.msg = win.MessageWindow({
            win.PushToTalkHook.PRESS: lambda w, l: self.on_press(),
            win.PushToTalkHook.RELEASE: lambda w, l: self.on_release(),
            win.PushToTalkHook.CANCEL: lambda w, l: self.on_cancel(),
            RESULT: lambda w, l: self.on_result(),
            STATUS: lambda w, l: self.on_status(),
            HIDE: lambda w, l: self.hide_if(w),
            win.WM_TIMER: lambda w, l: self.on_timer(w),
            win.WM_POWERBROADCAST: lambda w, l: self.on_power(w),
            win.WM_WTSSESSION_CHANGE: lambda w, l: self.on_session(w),
            win.WM_DEVICECHANGE: lambda w, l: self.on_device_change(w),
        })
        self.indicator = win.Indicator()
        self.hook = win.PushToTalkHook(self.msg, accept_injected)
        self.status_text = ""
        win.user32.SetTimer(self.msg.hwnd, TIMER_CONFIG, 3000, None)
        threading.Thread(target=self.worker, daemon=True).start()

    # ------------------------------------------------------------ worker thread
    def load_engine(self) -> None:
        self.engine = None  # drop the old model first (GPU memory)
        gc.collect()
        self.engine_error = ""
        self.unloaded = False
        self.write_status()
        try:
            t0 = time.perf_counter()
            self.engine = asr.create(self.config.voice_engine)
            log.info("engine %s ready in %.1fs", self.engine.name, time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001
            self.engine_error = str(e)
            log.exception("cannot load the speech engine")
        self.reload_queued = False
        self.last_used = time.monotonic()
        self.write_status()

    def maybe_unload(self) -> None:
        """Release the model after the idle time chosen in Settings (GPU
        memory, about 3 GB for Breeze). Off by default: the next press then
        has to wait for loading again."""
        minutes = self.config.voice_unload_minutes
        if (minutes <= 0 or self.engine is None or self.recording or not self.jobs.empty()
                or time.monotonic() - self.last_used < minutes * 60):
            return
        log.info("idle for %d minutes; releasing the speech engine", minutes)
        self.engine = None
        gc.collect()
        self.unloaded = True
        self.write_status()

    def write_status(self) -> None:
        """For the settings page: what is loaded, and is there a microphone."""
        e = self.engine
        state = ("ready" if e is not None else "error" if self.engine_error
                 else "unloaded" if self.unloaded else "loading")
        data = {"pid": os.getpid(), "state": state, "engine": getattr(e, "name", ""),
                "device": getattr(e, "device", "cpu") if e is not None else "",
                "error": self.engine_error, "mic": self.mic}
        try:
            tmp = status_path().with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(status_path())
        except OSError:
            pass

    def worker(self) -> None:
        self.load_engine()
        while True:
            try:
                job = self.jobs.get(timeout=UNLOAD_CHECK_SECONDS)
            except queue.Empty:
                self.maybe_unload()
                continue
            if job is None:
                return
            if isinstance(job, str):
                if job == RELOAD:
                    self.load_engine()
                continue
            self.recognize(*job)

    def recognize(self, audio, delivery: str) -> None:
        if self.engine is None and self.unloaded:
            self.load_engine()  # released while idle: the press did not get to load it first
        if self.engine is None:
            self.results.put(("error", self.engine_error or "語音模型無法載入", delivery))
            self.msg.post(RESULT)
            return
        try:
            t0 = time.perf_counter()
            mine = self._my_words()
            hot = " ".join(mine) if self.config.voice_hotwords else ""
            raw = self._transcribe(audio, hot)
            out = text.clean(raw, traditional=self.config.voice_traditional, known=mine)
            log.info("recognized %.1fs of audio in %.2fs (%d chars)",
                     len(audio) / asr.SAMPLE_RATE, time.perf_counter() - t0, len(out))
            self.results.put(("text", out, delivery))
        except Exception as e:  # noqa: BLE001
            log.exception("recognition failed")
            self.results.put(("error", f"辨識失敗：{e}", delivery))
        self.last_used = time.monotonic()
        self.msg.post(RESULT)

    def _transcribe(self, audio, hot: str) -> str:
        """A model on the GPU can fail every call after hibernation or a
        display driver reset, until it is loaded again: reload once and
        retry, instead of failing until the service restarts."""
        try:
            return self.engine.transcribe(audio, hot)
        except Exception:  # noqa: BLE001
            log.exception("recognition failed; loading the speech engine again and retrying once")
        self.load_engine()
        if self.engine is None:
            raise RuntimeError(self.engine_error or "語音模型無法載入")
        return self.engine.transcribe(audio, hot)

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
        """Right Ctrl down. Recording starts at once (no word is cut off),
        but nothing is shown until the key has been held MIN_SECONDS: a
        quick tap of right Ctrl opens the IME's symbol panel and must not
        flash "錄音中" or a microphone error."""
        if self.recording:
            return
        self.press_error = ""
        self.press_window = win.user32.GetForegroundWindow()
        self.last_used = time.monotonic()
        if self.engine is None and self.unloaded and not self.reload_queued:
            self.reload_queued = True
            self.jobs.put(RELOAD)  # load while the user talks, not after
        win.user32.SetTimer(self.msg.hwnd, TIMER_HELD, int(MIN_SECONDS * 1000), None)
        try:
            self.recorder.start()
        except RuntimeError as e:  # no microphone: a plain message, no traceback
            log.warning("%s", e)
            self.press_error = str(e)
            return
        except Exception as e:  # noqa: BLE001
            log.exception("cannot open the microphone")
            self.press_error = f"無法開啟麥克風：{e}"
            return
        self.recording = True
        self.recording_since = time.monotonic()

    def on_held(self) -> None:
        """MIN_SECONDS after the press: really push-to-talk, not a tap."""
        win.user32.KillTimer(self.msg.hwnd, TIMER_HELD)
        if not self.hook.down:
            return  # released (or became a shortcut) in time: it was a tap
        if self.press_error:
            self.flash(self.press_error, seconds=5)
        elif self.recording:
            self.on_tick()
            win.user32.SetTimer(self.msg.hwnd, TIMER_TICK, 1000, None)

    def on_tick(self) -> None:
        """The label counts the seconds: it is plainly recording, right now."""
        if not self.recording:
            win.user32.KillTimer(self.msg.hwnd, TIMER_TICK)
            return
        s = int(time.monotonic() - self.recording_since)
        name = self.engine.name if self.engine else "模型載入中"
        self.show(f"● 錄音中 {s // 60}:{s % 60:02d}（{name}）… 放開右 Ctrl 結束")

    def on_cancel(self) -> None:
        self.cancel_recording()

    def _stop_timers(self) -> None:
        win.user32.KillTimer(self.msg.hwnd, TIMER_HELD)
        win.user32.KillTimer(self.msg.hwnd, TIMER_TICK)

    def cancel_recording(self, message: str = "") -> None:
        """Close the microphone and throw the audio away: right Ctrl was
        part of a shortcut, so nothing was being said to us."""
        self._stop_timers()
        if self.recording:
            self.recording = False  # first: a failing stop must not leave it "recording"
            try:
                self.recorder.cancel()
            except Exception:  # noqa: BLE001
                log.exception("cannot close the microphone")
        if message:
            self.flash(message, seconds=4)
        else:
            self.indicator.hide()

    def on_release(self) -> None:
        self.finish_recording(TYPE)

    def finish_recording(self, delivery: str) -> None:
        """Stop and recognize. ``delivery`` says where the text may go:
        typed at the cursor (a normal release), typed only if the same
        window still has the focus (a release the hook missed), or put on
        the clipboard (sleep, lock)."""
        self._stop_timers()
        if not self.recording:
            return
        self.recording = False
        try:
            audio, seconds = self.recorder.stop()
        except Exception as e:  # noqa: BLE001 - e.g. the microphone was unplugged
            log.exception("cannot stop the recording")
            self.flash(f"錄音中斷：{e}")
            return
        if audio is None or seconds < MIN_SECONDS:
            self.indicator.hide()
            return
        self.show("… 辨識中")
        self.jobs.put((audio, delivery))

    def on_result(self) -> None:
        kind, value, delivery = self.results.get()
        if kind != "text":
            self.flash(value)
            return
        if not value:
            self.flash("沒有聽到內容")
            return
        if delivery == TYPE or (delivery == SAME_WINDOW and not self.locked
                                and win.user32.GetForegroundWindow() == self.press_window):
            self.indicator.hide()
            win.type_text(value)
            return
        if win.set_clipboard(self.msg.hwnd, value):
            self.notice(CLIPBOARD_NOTICE)
            return
        # the clipboard stayed busy: typing it beats losing it
        log.warning("clipboard unavailable; typing the recognized text instead")
        self.indicator.hide()
        win.type_text(value)

    def notice(self, message: str) -> None:
        """Something the user must see, held back while the screen is locked."""
        if self.locked:
            self.pending_notice = message
        else:
            self.flash(message, seconds=8)

    def on_status(self) -> None:
        self.show(self.status_text)

    def show(self, message: str) -> None:
        self.shown += 1
        self.indicator.show(message)

    def hide_if(self, shown: int) -> None:
        """A flash's timer hides only its own message: a later one (錄音中)
        used to vanish when an earlier flash ran out."""
        if shown == self.shown:
            self.indicator.hide()

    def flash(self, message: str, seconds: float = 2.5) -> None:
        self.show(message)
        shown = self.shown
        threading.Timer(seconds, lambda: self.msg.post(HIDE, shown)).start()

    def on_timer(self, which: int = TIMER_CONFIG) -> None:
        """Every few seconds: check the push-to-talk state, follow settings
        changes; exit when turned off."""
        if which == TIMER_HELD:
            self.on_held()
            return
        if which == TIMER_DEVICES:
            self.refresh_devices()
            return
        if which == TIMER_TICK:
            self.on_tick()
            return
        self.check_keys()
        cfg = Config.load(self.config_path)
        flag = restart.voice_flag()
        again = flag.exists()
        if again:
            flag.unlink(missing_ok=True)
        if not cfg.voice_enabled or again:
            # turned off, or 重新啟動輸入法: whoever asked starts a new one
            log.info("voice input turned off; exiting" if not again else "restart requested; exiting")
            self.hook.close()
            self.jobs.put(None)
            status_path().unlink(missing_ok=True)
            win.quit_message_loop()
            return
        changed = cfg.voice_engine != self.config.voice_engine
        self.config = cfg
        if changed:
            log.info("engine changed to %s; reloading", cfg.voice_engine)
            self.jobs.put(RELOAD)

    def check_keys(self) -> None:
        """The hook only knows what it was shown. A release it never saw
        (sleep, lock screen, UAC prompt) kept the microphone open and the
        audio growing (64 KB a second) until some other key was pressed,
        and a right Ctrl pressed first typed what had been recorded before
        the computer slept. A hook Windows removed made push-to-talk
        silently dead until the service restarted.

        A missed release still ends in text: what someone said is never
        thrown away (「使用者最氣的就是我講一天的話，你跟我說沒錄到」)."""
        held = win.key_down(win.VK_RCONTROL)
        since = time.monotonic() - self.hook.last_down
        if self.recording and release_missed(held, since):
            log.warning("right Ctrl is no longer held but its release was not seen; recognizing anyway")
            self.finish_recording(SAME_WINDOW)
            self.hook.reset()
            self.hook.reinstall()
        elif self.hook.down and release_missed(held, since):
            self.hook.reset()
        if held and not self.hook.down and since > REPEAT_GAP:
            self.hook_suspect += 1
            if self.hook_suspect >= 2:
                log.warning("right Ctrl is held but the keyboard hook sees nothing; installing it again")
                self.hook.reinstall()
                self.hook_suspect = 0
        else:
            self.hook_suspect = 0

    # ------------------------------------------------------------ sleep, lock, devices
    def on_power(self, event: int) -> None:
        """Going to sleep while recording: close the microphone now, and
        recognize what was said; it goes to the clipboard, since nobody
        knows where the focus will be after waking."""
        if event == win.PBT_APMSUSPEND:
            log.info("going to sleep")
            self.finish_recording(CLIPBOARD)
            self.hook.reset()
        elif event in (win.PBT_APMRESUMEAUTOMATIC, win.PBT_APMRESUMESUSPEND):
            log.info("resumed from sleep")
            self.after_wake()

    def on_session(self, event: int) -> None:
        if event == win.WTS_SESSION_LOCK:
            self.locked = True
            self.finish_recording(CLIPBOARD)
            self.hook.reset()
        elif event == win.WTS_SESSION_UNLOCK:
            self.locked = False
            self.after_wake()
            if self.pending_notice:
                message, self.pending_notice = self.pending_notice, ""
                self.flash(message, seconds=8)

    def after_wake(self) -> None:
        self.hook.reinstall()
        self.schedule_device_refresh()

    def on_device_change(self, event: int) -> None:
        if event == win.DBT_DEVNODES_CHANGED:  # a headset connected or removed
            self.schedule_device_refresh()

    def schedule_device_refresh(self) -> None:
        win.user32.SetTimer(self.msg.hwnd, TIMER_DEVICES, DEVICE_SETTLE_MS, None)  # restarts if pending

    def refresh_devices(self) -> None:
        """Re-read the audio devices (PortAudio lists them once) so Settings
        and the next recording see a headset connected since. Only when
        something changed: every re-read leaks two handles inside PortAudio
        (measured), and it used to run every 30 seconds — about 5,800 a day
        in a process that lives across sleeps for weeks."""
        win.user32.KillTimer(self.msg.hwnd, TIMER_DEVICES)
        if self.recording:
            self.schedule_device_refresh()  # never while recording
            return
        mic = microphone(refresh=True)
        if mic != self.mic:
            self.mic = mic
            self.write_status()


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
    restart.voice_flag().unlink(missing_ok=True)  # meant for the one before this
    VoiceService()
    win.run_message_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
