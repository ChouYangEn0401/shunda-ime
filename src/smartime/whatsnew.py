"""這一版的新功能 — and the red dots that point at them.

The user's rule (2026-11-17): every update or piece of news gets a red dot,
so people find out what changed without reading a changelog:

* a newer version is out → the tray icon's dot, the settings rail's 關於
  (``update.available``; not this module);
* a new *feature* arrived with an update → the tray icon's dot again, a dot
  on the settings rail item that holds it, and a 「新」 tag on its row;
* new *data* — words, phrases, symbols in the lexicon or the 更多符號 pack —
  gets **no** dot. It would only interrupt; it goes into the CHANGELOG.

Adding a feature: one ``Feature`` below (``view`` = the settings page's
``data-view``) and ``data-new="<id>"`` on its row in
``settings/ui/index.html``. Marked seen on purpose, never by passing by:
「看看」 on the 關於 card (jumps there), a click on the row's 「新」 tag, or
「全部標為看過」. Seen ones fold into the card's collapsed 更新紀錄.

Seen ids live in ``%APPDATA%\\SmartIME\\seen.json``. A fresh install starts
with everything seen (a newcomer has the 練習場 tour, not twenty dots); an
upgrade from a version without this file starts with nothing seen.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass

from . import paths

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Feature:
    id: str
    version: str  # the version that brought it
    view: str  # settings page (data-view)
    title: str
    text: str


# Newest first. Only features — never words, phrases or symbol data.
FEATURES: tuple[Feature, ...] = (
    Feature("palette-key", "0.10.0-beta.1", "keys", "符號面板可以改用左 Ctrl",
            "沒有右 Ctrl 的筆電：在「快捷鍵」把符號面板改成左 Ctrl（單按一下）。"),
    Feature("voice-key", "0.10.0-beta.1", "keys", "語音輸入可以改按住左 Ctrl",
            "按住說話的鍵也可以換成左 Ctrl；兩個用同一個鍵也行：短按開面板、按住才是語音。"),
    Feature("corrections-log", "0.10.0-alpha.2", "fix", "修正紀錄與「程式推薦」",
            "你改過的字（原本 → 改成、怎麼改的、幾次）都列在這裡；同一個修正做到第 2 次，就自動加進我的詞庫「程式推薦」。"),
    Feature("retype-swap", "0.10.0-alpha.2", "fix", "刪掉重打就換一個",
            "刪掉剛打的字、又打一樣的鍵、出來還是同一個字，會自動換成同音的下一個；Ctrl+Z 換回。"),
    Feature("dict-edit", "0.10.0-alpha.2", "dict", "詞庫裡的詞可以直接編輯",
            "我的詞庫每個詞都有「編輯」，直接改字或注音，不用只靠打字時按 Ctrl+D。"),
    Feature("update-quiet", "0.10.0-alpha.1.4", "about", "更新改成安靜安裝",
            "按「下載並安裝」（或自動安裝）後，只會跳出 Windows 的權限確認和一個進度條，不用再一頁一頁按下一步。"
            "網路不穩時下載會自己重試、接著下載。"),
    Feature("update-skip", "0.10.0-alpha.1.3", "about", "略過這個版本",
            "不想裝這一版：按「略過這個版本」，紅點就不亮了，有更新的版本才會再提醒。"),
    Feature("whatsnew-dots", "0.10.0-alpha.1.2", "about", "紅點告訴你哪裡有新東西",
            "更新之後，工作列圖示、設定頁左邊有新功能的那一頁、那一列都會標紅點。"
            "按「看看」帶你過去，看過的收進下面的更新紀錄。新的單字、片語不會亮紅點。"),
    Feature("update-auto-install", "0.10.0-alpha.1.1", "about", "找到新版本自動下載並開始安裝",
            "打開以後，知道有新版本就在背景下載、直接安靜安裝；Windows 的權限確認按「是」才會裝。"),
    Feature("update-time", "0.10.0-alpha.1.1", "about", "檢查更新的時間設到分鐘",
            "「什麼時候檢查」可以選每天或星期幾、幾點幾分。"),
    Feature("update-check", "0.10.0-alpha.1", "about", "自動檢查更新",
            "定期向 GitHub 查有沒有新版本（預設每週五下午），有的話工作列圖示出現紅點，右鍵第一項就能更新。"),
)
IDS = tuple(f.id for f in FEATURES)


def _path():
    return paths.user_dir() / "seen.json"


def ensure_baseline() -> None:
    """Create seen.json once. Call before anything creates the user's other
    files (config, user.db): their absence is how a fresh install is told
    from an upgrade."""
    p = _path()
    if p.exists():
        return
    upgraded = paths.config_path().exists() or paths.user_db_path().exists() or \
        (paths.user_dir() / "practice.json").exists()
    _write(set() if upgraded else set(IDS))


def _write(ids: set[str]) -> None:
    try:
        _path().parent.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps({"seen": sorted(ids)}, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        log.debug("cannot write seen.json", exc_info=True)


def seen() -> set[str]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return {str(x) for x in data.get("seen", [])}
    except (OSError, ValueError, AttributeError):
        return set(IDS)  # no file (or a broken one): no dots rather than a stuck one


def unseen() -> list[Feature]:
    s = seen()
    return [f for f in FEATURES if f.id not in s]


def mark_seen(ids=None) -> int:
    """Mark ``ids`` (all features when None) as seen; returns how many
    were new."""
    s = seen()
    add = set(IDS if ids is None else ids) & set(IDS)
    fresh = add - s
    if fresh:
        _write(s | fresh)
    return len(fresh)


def listing() -> list[dict]:
    s = seen()
    return [{**asdict(f), "seen": f.id in s} for f in FEATURES]


# The tray icon asks on every key: read the file at most every few seconds.
_cache = {"mtime": -1.0, "looked": 0.0, "count": 0}
LOOK_EVERY = 5.0


def unseen_count(now: float | None = None) -> int:
    now = time.time() if now is None else now
    if now - _cache["looked"] < LOOK_EVERY:
        return _cache["count"]
    _cache["looked"] = now
    try:
        mtime = _path().stat().st_mtime
    except OSError:
        mtime = 0.0
    if mtime != _cache["mtime"]:
        _cache["mtime"] = mtime
        _cache["count"] = len(unseen())
    return _cache["count"]
