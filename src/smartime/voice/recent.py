"""錄音暫存: what voice input recognized lately, for the symbol panel.

Recognized text is typed into whatever window has the focus when it is
ready; switching windows too soon used to lose it for good (reported:
「語音如果錄完結果太快我跳轉，我的錄音文字就會永遠消失」). The voice
service adds every result here, and the symbol panel's 錄音暫存 tab lists
them, newest first, to type again.

Kept only for a while (Settings: ``voice_keep_minutes``; 0 = until the IME
restarts) and never across a restart: the backend clears it when it starts.
It is what was said, so it is not meant to stay on disk.
"""

from __future__ import annotations

import json
import logging
import time

from .. import paths

log = logging.getLogger(__name__)

MAX_ITEMS = 30
KEEP_CHOICES = (5, 15, 30, 60, 180, 0)  # minutes; 0 = until the IME restarts
DEFAULT_KEEP = 30


def _path():
    return paths.user_dir() / "voice_recent.json"


def _read() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict) and isinstance(d.get("text"), str)
            and isinstance(d.get("at"), (int, float))]


def _write(items: list[dict]) -> None:
    try:
        _path().parent.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    except OSError:
        log.debug("cannot write voice_recent.json", exc_info=True)


def _fresh(items: list[dict], keep_minutes: int, now: float) -> list[dict]:
    if keep_minutes <= 0:
        return items
    return [d for d in items if now - d["at"] <= keep_minutes * 60]


def add(text: str, keep_minutes: int = DEFAULT_KEEP, now: float | None = None) -> None:
    text = text.strip()
    if not text:
        return
    now = time.time() if now is None else now
    items = [{"text": text, "at": now}] + _fresh(_read(), keep_minutes, now)
    _write(items[:MAX_ITEMS])


def items(keep_minutes: int = DEFAULT_KEEP, now: float | None = None) -> list[dict]:
    """[{"text", "at"}], newest first, the expired ones left out."""
    now = time.time() if now is None else now
    return _fresh(_read(), keep_minutes, now)


def clear() -> None:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.debug("cannot remove voice_recent.json", exc_info=True)


def age_label(at: float, now: float | None = None) -> str:
    """剛剛 / 3 分鐘前 / 1 小時前."""
    s = max(0, int((time.time() if now is None else now) - at))
    if s < 60:
        return "剛剛"
    if s < 3600:
        return f"{s // 60} 分鐘前"
    return f"{s // 3600} 小時前"
