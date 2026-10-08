"""The optional, bigger symbol catalogue (tools/build_symbols_extra.py, a few
thousand plain-BMP Unicode symbols): not bundled with the app, fetched from
GitHub only when the user turns it on and presses download — a toggle plus a
button in Settings, the same shape as the voice models (voice/models.py).
Startup stays exactly as fast as before for anyone who never does.

Kept in the user's own roamed data folder (small, like config.json and
recent-symbols.json) — not %LOCALAPPDATA%\\...\\models, which is for the
multi-gigabyte speech models.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .. import __version__, paths
from ..update import REPO

log = logging.getLogger(__name__)

URL = f"https://raw.githubusercontent.com/{REPO}/main/data/extra/symbols_extra.json"
USER_AGENT = f"ShundaIME/{__version__} (+https://github.com/{REPO})"
TIMEOUT = 15.0


def path() -> Path:
    return paths.user_dir() / "symbols-extra.json"


def status() -> dict:
    count = len(load())
    return {"installed": count > 0, "count": count}


def download(progress: Callable[[int, int], None] | None = None) -> Path:
    """Fetch the catalogue. Blocking; a few hundred KB, no resume needed."""
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https URL
        total = int(resp.headers.get("Content-Length") or 0)
        data = bytearray()
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            data.extend(chunk)
            if progress:
                progress(len(data), total)
    parsed = json.loads(bytes(data).decode("utf-8"))
    if not isinstance(parsed, list):
        raise ValueError("意外的符號檔格式")
    target = path()
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(bytes(data))
    tmp.replace(target)
    return target


def load() -> list[tuple[str, str, tuple[str, ...]]]:
    """The downloaded entries, or [] if never downloaded / unreadable."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for row in data:
        if not (isinstance(row, list) and len(row) == 3):
            continue
        sym, cat, tags = row
        if (isinstance(sym, str) and len(sym) == 1 and ord(sym) <= 0xFFFF
                and isinstance(cat, str) and cat and isinstance(tags, list)):
            out.append((sym, cat, tuple(str(t).lower() for t in tags)))
    return out
