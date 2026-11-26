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

Only what changed **from the version you had to this one** is listed (user,
2026-11-24: 「更新日誌未來只需要紀錄 from X to Y 中間的變化，不用全部列出來」).
seen.json also keeps ``version`` (the one that last ran) and ``from`` (the
lower end of the range shown). When the version changes, ``from`` moves up
to the old version — unless something in the old range was never looked
at; then it stays, so skipping a version cannot hide its news.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass

from . import __version__, paths

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
    Feature("suspect-next", "0.11.0-alpha.7", "fix", "修正模式按 n：跳到可疑的字",
            "按 Esc 進修正模式後按 n，游標跳到輸入法自己最拿不準的字（同音字分數很接近的地方），"
            "提示列說「在」還是「再」？；j 換、n 下一個。只是一個鍵，不加新模式。"),
    Feature("quick-prefix", "0.11.0-alpha.6", "snippets", "快速詞：打開頭也會建議",
            "直接打快速詞文字的前 3 個字（opu → opus-5.5-medium），提示列一樣用橘色建議，按 Tab 才換成整段。"
            "觸發字裡有鍵被當成雜鍵略過時，快速詞也照樣出現在「略過」旁邊。"),
    Feature("dict-cleanup", "0.11.0-alpha.4", "dict", "詞庫的整理建議",
            "列出可能用不到的詞：只用過一次、很久沒用、英文像打錯的。勾選後刪除；只看自動收集的詞。"),
    Feature("punct-fullwidth", "0.11.0-alpha.4", "punct", "＠＃＄％＆＊ 也有鍵了",
            "Ctrl+Shift+2 3 4 5 7 8，跟 Ctrl+Shift+9 0 打（）一樣：上排符號的全形。"
            "Ctrl+- 和 Ctrl+/ 沒在打字時交給程式，縮小、切換註解不再失靈。"),
    Feature("zhuyin", "0.11.0-alpha.2", "typing", "國字可以直接換成注音",
            "候選窗最後一組「注音」：這個字（天 → ㄊㄧㄢ）或整段（你好 → ㄋㄧˇㄏㄠˇ），選了就換成注音。"
            "修正模式裡按 z，游標上的字換成注音，再按一次換回國字。"),
    Feature("cand-page", "0.11.0-alpha.2", "typing", "候選窗寫出現在在第幾頁",
            "右上角「第 3／27 頁」，不在第 1 頁時用藍底標出來；按 Home 一下回到第 1 頁，最常用的詞都在那裡。"),
    Feature("composing-hint", "0.11.0-alpha.1", "typing", "還沒送出的字，提示會說怎麼送出",
            "游標旁的小點多了「Enter 送出」：對了就按 Enter，後面再打什麼都動不到它。可以換回只有一個點，或一支筆。"),
    Feature("palette-idle", "0.11.0-alpha.1", "punct", "沒在打字時也是新的符號面板",
            "什麼都沒打時單按 Ctrl，出來的也是同一個符號面板。分頁多了「快速詞」，忘了觸發字可以從這裡選。"),
    Feature("practice-steps", "0.11.0-alpha.1", "practice", "練習場多了三步",
            "看到對了就 Shift+Enter 送出、快速詞（打「順」按 Tab）、找回剛剛說的話（錄音暫存）。"
            "標著「新」的就是；不想練也可以點「新」收起來。"),
    Feature("quick-words", "0.10.1", "snippets", "快速詞：打開頭就打出一整段",
            "設一個觸發字（例：art → artifact、順 → 順打輸入法好棒 !!），打到它提示列就用橘色建議，"
            "按 Tab 直接打出。文字可以自己寫，也可以直接連到一筆片語。"),
    Feature("suggest-rows", "0.10.1", "typing", "接續建議分兩行：你的在上面",
            "提示列上面一行是你自己的（橘色快速詞、紫色你打過或加過的詞），下面一行藍色是詞庫原本的建議。"
            "Tab 帶入第一個，Ctrl+數字帶入其他的。"),
    Feature("voice-recent", "0.10.1", "voice", "錄音暫存：語音的字不會再弄丟",
            "每次辨識的結果都留在符號面板的「錄音暫存」分頁（單按 Ctrl 再按 Tab）。"
            "切視窗太快、字沒打進去，從那裡再打一次就好；留多久在這裡設定。"),
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
            "更新時只會看到 Windows 的權限確認和一個進度條，不用一頁頁按下一步。下載中斷會自己重試。"),
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


def _vt(v: str) -> tuple:
    from .update import version_tuple

    return version_tuple(v)


def _read() -> dict | None:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write(ids: set[str], since: str | None) -> None:
    data = {"seen": sorted(ids), "version": __version__, "from": since}
    try:
        _path().parent.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        log.debug("cannot write seen.json", exc_info=True)


def _in_range(f: Feature, since: str | None) -> bool:
    v = _vt(f.version)
    return (since is None or v > _vt(since)) and v <= _vt(__version__)


def _guess_from(seen_ids: set[str]) -> str | None:
    """A seen.json from before ``from`` existed: the newest version whose
    features, and every older one's, were all looked at."""
    best = None
    for f in sorted(FEATURES, key=lambda f: _vt(f.version)):
        if f.id not in seen_ids:
            break
        best = f.version
    return best


def ensure_baseline() -> None:
    """Create seen.json once, and move the listed range when the version
    changed. Call before anything creates the user's other files (config,
    user.db): their absence is how a fresh install is told from an upgrade."""
    data = _read()
    if data is None:
        upgraded = paths.config_path().exists() or paths.user_db_path().exists() or \
            (paths.user_dir() / "practice.json").exists()
        if upgraded:
            _write(set(), since=None)  # from a version without this file: all of it is news
        else:
            _write(set(IDS), since=__version__)  # a newcomer: none of it is
        return
    if data.get("version") == __version__:
        return
    seen_ids = {str(x) for x in data.get("seen", [])}
    old = data.get("version")
    since = data.get("from") if old else _guess_from(seen_ids)
    if old and all(f.id in seen_ids for f in FEATURES
                   if _in_range(f, since) and _vt(f.version) <= _vt(old)):
        since = old  # the old range was all looked at: only what came after it
    _write(seen_ids, since=since)


def _state() -> tuple[set[str], str | None]:
    data = _read()
    if data is None:
        return set(IDS), __version__  # no file (or a broken one): no dots rather than a stuck one
    return {str(x) for x in data.get("seen", [])}, data.get("from")


def seen() -> set[str]:
    return _state()[0]


def since() -> str | None:
    """The version the listed range starts after (None = from the start)."""
    return _state()[1]


def current() -> list[Feature]:
    """The features between the version you had and this one."""
    frm = since()
    return [f for f in FEATURES if _in_range(f, frm)]


def unseen() -> list[Feature]:
    s = seen()
    return [f for f in current() if f.id not in s]


def mark_seen(ids=None) -> int:
    """Mark ``ids`` (every listed feature when None) as seen; returns how
    many were new."""
    s, frm = _state()
    add = {f.id for f in current()} if ids is None else set(ids) & set(IDS)
    fresh = add - s
    if fresh:
        _write(s | fresh, since=frm)
    return len(fresh)


def listing() -> list[dict]:
    s = seen()
    return [{**asdict(f), "seen": f.id in s} for f in current()]


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
