"""Open the settings window: ``python -m smartime.settings``.

* One instance per user: a second launch just opens another window on the
  running server (address and token in %APPDATA%\\SmartIME\\settings-server.json).
* The page runs in an Edge (or Chrome) "app" window — no tabs or address bar.
  Without either browser the default browser is used.
* The server exits about a minute after the last window stops pinging.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from .. import paths
from .api import SettingsApp, SettingsServer

log = logging.getLogger("smartime.settings")
IDLE_EXIT_SECONDS = 75
WINDOW_SIZE = "1200,860"


def _state_file() -> Path:
    return paths.user_dir() / "settings-server.json"


def _running_url() -> str | None:
    """URL of an already running settings server, if it answers."""
    try:
        info = json.loads(_state_file().read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(info['port'])}/"
        req = urllib.request.Request(url + "api/ping", headers={"X-SmartIME-Token": info["token"]})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                return f"{url}?t={info['token']}"
    except Exception:  # noqa: BLE001 - not running / stale file
        return None
    return None


def _browser() -> list[str] | None:
    """Edge or Chrome, for --app windows."""
    candidates = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for c in candidates:
        if c.is_file():
            return [str(c)]
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def open_window(url: str) -> None:
    browser = _browser()
    if browser:
        subprocess.Popen(browser + [f"--app={url}", f"--window-size={WINDOW_SIZE}"], close_fds=True)
    else:
        webbrowser.open(url)


def _setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(
        paths.log_dir() / "settings.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _setup_logging()
    no_window = "--no-window" in argv
    section = next((a.split("=", 1)[1] for a in argv if a.startswith("--section=")), "")
    anchor = f"#{section}" if section.isalpha() else ""

    url = _running_url()
    if url:
        log.info("settings server already running; opening a window")
        if not no_window:
            open_window(url + anchor)
        return 0

    app = SettingsApp()
    token = secrets.token_urlsafe(24)
    server = SettingsServer(app, token)
    _state_file().write_text(json.dumps({"port": server.port, "token": token, "pid": os.getpid()}),
                             encoding="utf-8")
    url = f"http://127.0.0.1:{server.port}/?t={token}"
    log.info("settings server on port %s", server.port)
    if no_window:
        print(url, flush=True)
    else:
        open_window(url + anchor)

    def watchdog() -> None:
        while True:
            time.sleep(5)
            if app.busy():
                app.last_ping = time.monotonic()  # finish a model download / install first
            elif time.monotonic() - app.last_ping > IDLE_EXIT_SECONDS:
                log.info("no window for %ss; exiting", IDLE_EXIT_SECONDS)
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        app.close()
        try:
            info = json.loads(_state_file().read_text(encoding="utf-8"))
            if info.get("pid") == os.getpid():
                _state_file().unlink()
        except (OSError, ValueError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
