"""Start the voice service from the IME backend or the settings app, using a
Python that has the voice packages (the IME's own embeddable Python does
not). Lookup order:

1. SMARTIME_VOICE_PYTHON (explicit)
2. %LOCALAPPDATA%\\SmartIME\\voice-runtime\\pythonw.exe (installed component)
3. <repo>\\.venv\\Scripts\\pythonw.exe (development checkout)
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

from .. import paths

MUTEX = "Local\\SmartIME.Voice"
SYNCHRONIZE = 0x00100000


def voice_python() -> Path | None:
    env = os.environ.get("SMARTIME_VOICE_PYTHON")
    candidates = [Path(env)] if env else []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "SmartIME" / "voice-runtime" / "pythonw.exe")
    candidates.append(paths.app_root() / ".venv" / "Scripts" / "pythonw.exe")
    for c in candidates:
        if c.is_file():
            return c
    return None


def running() -> bool:
    if os.name != "nt":
        return False
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenMutexW.restype = ctypes.c_void_p
    handle = k32.OpenMutexW(SYNCHRONIZE, False, MUTEX)
    if handle:
        k32.CloseHandle(ctypes.c_void_p(handle))
        return True
    return False


def start() -> bool:
    """Start the service unless it runs already. True if (now) running or
    started; False if no suitable Python is installed."""
    if running():
        return True
    py = voice_python()
    if py is None:
        return False
    src = paths.app_root() / "src"
    code = (f"import sys; sys.path.insert(0, r'{src}'); "
            "from smartime.voice.service import main; sys.exit(main())")
    subprocess.Popen([str(py), "-c", code], cwd=str(paths.app_root()), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    return True
