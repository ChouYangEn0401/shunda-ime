"""重新啟動輸入法: start the backend and the voice service afresh.

Asked for so that a strange state never needs a reboot or a sign-out: a
stuck panel, a composition that carried over into another field, whatever
a long-running process may have piled up. Only our own processes restart:
PIMELauncher starts the backend again by itself as soon as it exits (that is
why scripts/dev-reload.ps1 has to stop the launcher first), and every app's
next key gets a fresh session. The launcher itself is left alone — quitting
it would leave the computer without the input method if starting it again
failed. Settings, dictionary and memory are files and stay as they are.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes

from . import paths

log = logging.getLogger(__name__)
PROCESS_TERMINATE, PROCESS_QUERY_LIMITED_INFORMATION = 0x0001, 0x1000


def _pid_file():
    return paths.user_dir() / "backend.pid"


def voice_flag():
    """The voice service exits when it finds this (checked every 3 s)."""
    return paths.user_dir() / "voice-restart"


def record_backend() -> None:
    """At backend start-up: which process to restart."""
    try:
        _pid_file().parent.mkdir(parents=True, exist_ok=True)
        _pid_file().write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass


def request_voice_restart() -> None:
    try:
        voice_flag().parent.mkdir(parents=True, exist_ok=True)
        voice_flag().write_text("", encoding="ascii")
    except OSError:
        pass


def exit_backend_soon(delay: float = 0.3) -> None:
    """Inside the backend (the tray menu): exit once this reply is out;
    the launcher starts a new backend for the next key."""
    request_voice_restart()

    def go() -> None:
        log.info("restart requested; backend exiting")
        logging.shutdown()
        os._exit(0)

    threading.Timer(delay, go).start()


def _image_name(handle) -> str:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(len(buf))
    if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        return ""
    return os.path.basename(buf.value).lower()


def restart_backend() -> bool:
    """From the settings app: end the backend process; True if one was
    running. Only a Python process with the recorded id is touched (an id
    can be reused by an unrelated program after a reboot)."""
    request_voice_restart()
    try:
        pid = int(_pid_file().read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    if os.name != "nt" or pid == os.getpid():
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        if _image_name(handle) not in ("python.exe", "pythonw.exe"):
            return False
        ok = bool(k32.TerminateProcess(handle, 0))
        log.info("restart: backend %d ended (%s)", pid, ok)
        return ok
    finally:
        k32.CloseHandle(handle)


def start_voice_when_gone(start, running, timeout: float = 10.0) -> None:
    """After a restart: start the voice service again once the old one has
    seen the flag and exited (in the background, the page does not wait)."""
    def go() -> None:
        end = time.monotonic() + timeout
        while running() and time.monotonic() < end:
            time.sleep(0.25)
        if not running():
            start()

    threading.Thread(target=go, daemon=True).start()
