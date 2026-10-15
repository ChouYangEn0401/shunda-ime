"""重新啟動輸入法: the backend process ends (the launcher starts a new one),
the voice service exits at its next check, and nothing else is touched."""

import subprocess
import sys
import time

from smartime import restart


def test_the_recorded_backend_is_ended():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        restart._pid_file().parent.mkdir(parents=True, exist_ok=True)
        restart._pid_file().write_text(str(child.pid), encoding="ascii")
        assert restart.restart_backend()
        assert child.wait(5) is not None
        assert restart.voice_flag().exists()  # the voice service restarts too
    finally:
        if child.poll() is None:
            child.kill()


def test_nothing_happens_without_a_recorded_python_backend(tmp_path):
    assert not restart.restart_backend()  # no pid file
    notepad = subprocess.Popen(["cmd", "/c", "ping -n 30 127.0.0.1 >nul"], creationflags=0x08000000)
    try:
        restart._pid_file().write_text(str(notepad.pid), encoding="ascii")
        assert not restart.restart_backend()  # not a Python process: left alone
        assert notepad.poll() is None
    finally:
        notepad.kill()


def test_record_backend_writes_this_process():
    import os

    restart.record_backend()
    assert restart._pid_file().read_text(encoding="ascii") == str(os.getpid())
    assert not restart.restart_backend()  # never ends the process asking


def test_voice_service_exits_on_the_flag(tmp_path, monkeypatch):
    from smartime.voice import service, win

    import types

    from smartime.config import Config

    monkeypatch.setattr(win.user32, "SetTimer", lambda *a: 1)
    monkeypatch.setattr(win.user32, "KillTimer", lambda *a: 1)
    monkeypatch.setattr(win, "key_down", lambda vk: False)
    quit_ = []
    monkeypatch.setattr(win, "quit_message_loop", lambda: quit_.append(1))
    s = object.__new__(service.VoiceService)
    s.hook = types.SimpleNamespace(down=False, combo=False, last_down=time.monotonic(), close=lambda: None,
                                   reset=lambda: None, reinstall=lambda: None)
    s.recording, s.hook_suspect = False, 0
    s.jobs = __import__("queue").Queue()
    cfg = Config()
    cfg.voice_enabled = True
    s.config_path = tmp_path / "config.json"
    cfg.save(s.config_path)
    s.config = cfg
    s.on_timer(service.TIMER_CONFIG)
    assert not quit_  # no flag: keeps running
    restart.request_voice_restart()
    s.on_timer(service.TIMER_CONFIG)
    assert quit_ == [1] and s.jobs.get_nowait() is None and not restart.voice_flag().exists()


def test_settings_restart_button(monkeypatch):
    from smartime.settings.api import SettingsApp

    monkeypatch.setattr(restart, "restart_backend", lambda: True)
    app = SettingsApp()
    try:
        assert app.restart_ime() == {"backend": True, "voice": False}
    finally:
        app.close()
