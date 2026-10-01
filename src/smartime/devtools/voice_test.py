"""Voice input, end to end on the real desktop, without a microphone:

    python -m smartime.devtools.voice_test [--engine auto|breeze|sensevoice] [--wav FILE --expect TEXT]

A recorded clip stands in for the microphone; everything else is real: the
push-to-talk hook (right Ctrl pressed with SendInput), the recognizer, the
cleanup and typing the result into a text box with this IME active (so the
IME must let the typed text through). Checks:

1. hold right Ctrl, release  -> the clip's text appears in the box
2. right Ctrl + A (shortcut) -> cancelled, nothing typed
3. a quick tap               -> ignored, nothing typed

Like tsf_typing_test it waits until the keyboard and mouse have been idle
for 5 s and stops at once if you touch them. Settings and dictionary come
from a temporary folder; your own are not read or changed.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path

from . import tsf_typing_test as tt

VK_RCONTROL = 0xA3
VK_A = 0x41


def load_wav(path: Path):
    import numpy as np

    with wave.open(str(path)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"{path}: need 16-bit mono WAV")
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if rate != 16000:
        n = int(len(data) * 16000 / rate)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)
    return data


class ClipRecorder:
    """Stands in for the microphone: "records" for as long as the key is held
    and returns the clip."""

    def __init__(self, audio) -> None:
        self.audio = audio
        self.started = 0.0

    def start(self) -> None:
        self.started = time.monotonic()

    def stop(self):
        return self.audio, time.monotonic() - self.started


def _arg(name: str, default: str = "") -> str:
    argv = sys.argv[1:]
    return argv[argv.index(name) + 1] if name in argv else default


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    engine = _arg("--engine", "auto")
    user_dir = Path(tempfile.mkdtemp(prefix="smartime-voice-test-"))
    os.environ["SMARTIME_USER_DIR"] = str(user_dir)

    from ..config import Config
    from ..voice import models
    from ..voice.service import VoiceService

    wav = Path(_arg("--wav") or models.models_dir() / "sensevoice-int8" / "test_wavs" / "zh.wav")
    expect = _arg("--expect", "" if _arg("--wav") else "開放時間")
    if not wav.is_file():
        print(f"no test clip at {wav}; pass --wav FILE (16-bit mono WAV) and --expect TEXT")
        return 2
    cfg = Config()
    cfg.voice_enabled, cfg.voice_engine = True, engine
    cfg.save(user_dir / "config.json")
    audio = load_wav(wav)

    print("waiting until keyboard/mouse have been idle for 5 s ...")
    if not tt.wait_until_idle():
        print("ABORT: the computer is in use; try again later (no keys were sent)")
        return 2
    tt.ole32.CoInitializeEx(None, 0x2)
    mgr = tt.ProfileMgr()
    previous = mgr.active()
    tt.GUARD = tt.UserGuard()
    box = tt.TestWindow()
    service = None
    failures = 0
    try:
        service = VoiceService(recorder=ClipRecorder(audio), accept_injected=True)
        box.set_caption(f"  智慧輸入法語音自動測試（碰鍵盤或滑鼠會立即停止）\r\n  載入模型中…（{engine}）")
        deadline = time.monotonic() + 120
        while service.engine is None and not service.engine_error and time.monotonic() < deadline:
            tt.pump(0.1)
        if service.engine is None:
            print("FAIL: engine did not load:", service.engine_error or "timeout")
            return 1
        print(f"engine: {service.engine.name} ({getattr(service.engine, 'device', 'cpu')})")
        if not box.focus():
            print("ABORT: could not bring the test window to the foreground; no keys were sent")
            return 2
        hr = mgr.activate(tt.TF_PROFILETYPE_INPUTPROCESSOR, 0x0404, tt.guid(tt.PIME_CLSID), tt.guid(tt.PROFILE_GUID),
                          None, tt.TF_IPPMF_FORPROCESS | tt.TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        if hr != 0:
            print(f"FAIL: ActivateProfile returned {hr & 0xFFFFFFFF:#x}")
            return 1
        tt.pump(0.8)

        def wait_text(seconds: float) -> str:
            end = time.monotonic() + seconds
            while time.monotonic() < end and not box.text():
                tt.pump(0.05)
            tt.pump(0.3)  # the rest of the text
            return box.text()

        # 1. hold, release
        box.set_caption(f"  1/3 按住右 Ctrl 說話（用錄好的 {wav.name} 代替麥克風）")
        box.clear()
        box._send(VK_RCONTROL, False)
        tt.pump(0.8)
        box._send(VK_RCONTROL, True)
        t0 = time.monotonic()
        got = wait_text(30)
        ok = bool(got) and expect in got
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  hold + release -> {got!r} ({time.monotonic() - t0:.2f}s after release)"
              + ("" if ok else f"  (expected to contain {expect!r})"))

        # 2. right Ctrl + A is a shortcut: cancelled
        box.set_caption("  2/3 右 Ctrl + A 是快速鍵：不應該打出任何字")
        box.clear()
        box._send(VK_RCONTROL, False)
        tt.pump(0.5)
        box._send(VK_A, False)
        box._send(VK_A, True)
        box._send(VK_RCONTROL, True)
        got = wait_text(3)
        failures += bool(got)
        print(f"{'PASS' if not got else 'FAIL'}  right Ctrl + A  -> {got!r}")

        # 3. a quick tap is not a recording
        box.set_caption("  3/3 輕按一下右 Ctrl：不應該打出任何字")
        box.clear()
        box._send(VK_RCONTROL, False)
        box._send(VK_RCONTROL, True)
        got = wait_text(3)
        failures += bool(got)
        print(f"{'PASS' if not got else 'FAIL'}  quick tap       -> {got!r}")
        return 1 if failures else 0
    except tt.Aborted as e:
        print("ABORT:", e)
        return 2
    finally:
        if service is not None:
            service.hook.close()
            service.jobs.put(None)
            service.indicator.hide()
        mgr.activate(previous.dwProfileType, previous.langid, previous.clsid, previous.guidProfile,
                     previous.hkl, tt.TF_IPPMF_FORPROCESS | tt.TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE)
        box.destroy()
        tt.GUARD.close()
        tt.pump(0.1)
        shutil.rmtree(user_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
