"""修字練習: practice levels for correction mode, their progress, and the
"practising" flag that keeps the IME from learning anything meanwhile.

Every sentence is made up for this page (never the user's own text — the
user asked for that, for privacy), and every level is a mistake the IME
really makes with an empty dictionary: tests/test_practice.py types each
one, checks that it comes out wrong, applies the hint's keys and checks the
result. A level whose sentence the IME starts getting right fails there,
instead of becoming a level with nothing to fix.

The settings page shows the levels; the user types into a text box there
with the real IME. While that box has the focus the page keeps
``practice.json``'s ``until`` a few seconds ahead, and the IME learns
nothing until it lapses (a closed page cannot leave it on).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from . import paths

ACTIVE_SECONDS = 20  # the page renews it every few seconds while the box has the focus


@dataclass(frozen=True)
class Level:
    id: str
    title: str
    skill: str  # what it teaches, shown as a tag
    type_text: str  # what to type, the usual way (the keys come from it)
    wrong: str  # what the IME makes of it, empty dictionary
    target: str  # what the box must say at the end
    hint: str  # the fix, in words (HTML: <kbd>)
    fix: str  # the fix as simulator keys, after typing (tests); {T:字} = the keys that type 字
    note: str = ""  # what to type differently, when type_text is not the target


LEVELS: tuple[Level, ...] = (
    Level("swap", "換一個字", "j 換字",
          "你先走吧", "你先走八", "你先走吧",
          "按 <kbd>Esc</kbd> 進修正模式，游標就在「八」上，按 <kbd>j</kbd> 換成下一個最可能的字，<kbd>Enter</kbd> 送出。",
          "{ESC}j"),
    Level("list", "從選字窗挑", "↓ 選字",
          "記得帶雨傘", "記得代雨傘", "記得帶雨傘",
          "<kbd>Esc</kbd>，<kbd>h</kbd> 往左移到「代」，<kbd>↓</kbd> 打開選字窗，按「帶」前面的數字。",
          "{ESC}hh{DOWN}{PICK:帶}"),
    Level("word", "換一整個詞", "↓ 選詞",
          "他的公式很複雜", "他的公視很複雜", "他的公式很複雜",
          "<kbd>Esc</kbd>，移到「公」，<kbd>↓</kbd>：最上面是從這裡開始的詞，選「公式」。",
          "{ESC}hhhh{DOWN}{PICK:公式}"),
    Level("english", "英文旁邊的字", "h l 移動",
          "明天見bye", "明天建bye", "明天見bye",
          "<kbd>Esc</kbd> 後游標在 bye 上；在英文字裡 <kbd>h</kbd> 一次走一個字母，走到「建」再按 <kbd>j</kbd>。",
          "{ESC}hhhj"),
    Level("tone", "打錯聲調", "聲調鍵",
          "我想買房子", "我想買防子", "我想賣房子",
          "<kbd>Esc</kbd>，移到「買」，直接按第四聲的聲調鍵：ㄇㄞˇ 變 ㄇㄞˋ「賣」。再 <kbd>l</kbd> 到「防」按 <kbd>j</kbd>。",
          "{ESC}hh{T:ˋ}lj",
          note="故意打錯，等一下改成「賣」"),
    Level("retype", "整個音打錯", "r 重打",
          "今天很樂", "今天很樂", "今天很熱",
          "<kbd>Esc</kbd>（游標在「樂」），按 <kbd>r</kbd> 刪掉它的注音，重打「熱」ㄖㄜˋ；打完自動回到修正模式。",
          "{ESC}r{T:熱}",
          note="故意打錯，等一下改成「熱」"),
    Level("dropped", "救回被略過的鍵", "略過的鍵",
          "e化的流程", "畫的流程", "e化的流程",
          "e 被當成手滑略過了。<kbd>Esc</kbd>，移到「畫」，面板會說「略過了 e」；<kbd>↓</kbd> 選 e 把它留下來，"
          "再 <kbd>l</kbd> 回到「畫」按 <kbd>j</kbd> 換成「化」。",
          "{ESC}hhh{DOWN}{PICK:e}lj"),
    Level("extra", "刪掉多打的鍵", "x 刪",
          "我好q", "我好q", "我好",
          "<kbd>Esc</kbd>（游標在 q 上），按 <kbd>x</kbd> 刪掉。",
          "{ESC}x",
          note="最後故意多打一個 q"),
    Level("regroup", "英文吃掉了下一個字", "↓ 重新分組",
          "這個game你玩過嗎", "這個games以玩過嗎", "這個game你玩過嗎",
          "game 後面沒空白，「你」的第一個鍵被當成 s。<kbd>Esc</kbd>，移到「以」，面板會提示；"
          "<kbd>↓</kbd> 最上面的「重新分組」選 game｜你。",
          "{ESC}hhh{DOWN}{PICK:game｜你}"),
    Level("number", "數字吃掉了注音", "↓ 重新分組",
          "排行榜前10大", "排行榜前10284", "排行榜前10大",
          "「大」的注音鍵也是數字鍵，整串被讀成 10284。<kbd>Esc</kbd>，<kbd>↓</kbd> 選 10｜大。",
          "{ESC}{DOWN}{PICK:10｜大}"),
    Level("edge", "自己移分界", "Shift+←/→",
          "排行榜前10大", "排行榜前10284", "排行榜前10大",
          "同一句，這次不用選字窗：<kbd>Esc</kbd>，按 <kbd>Shift</kbd>+<kbd>←</kbd> 把數字後面的分界往左推，"
          "看面板上的琥珀色直線，推到 10｜大 就停，按任何鍵確定。",
          "{ESC}{S-LEFT}{S-LEFT}{S-LEFT}"),
    Level("combo", "一句兩個錯", "綜合",
          "OK啦你先走吧", "OK拉你先走八", "OK啦你先走吧",
          "兩個都是同音字：<kbd>Esc</kbd> 先在「八」按 <kbd>j</kbd>，再往左移到「拉」按 <kbd>j</kbd>。"
          "按錯了就 <kbd>u</kbd> 復原。",
          "{ESC}jhhhhj"),
)


def _path():
    return paths.user_dir() / "practice.json"


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def active() -> bool:
    """The practice box has the focus: learn nothing."""
    until = _load().get("until", 0)
    return isinstance(until, (int, float)) and time.time() < until


def set_active(on: bool) -> None:
    data = _load()
    data["until"] = time.time() + ACTIVE_SECONDS if on else 0
    _save(data)


def done() -> list[str]:
    ids = _load().get("done", [])
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def mark_done(level_id: str) -> list[str]:
    if level_id not in {lv.id for lv in LEVELS}:
        return done()
    data = _load()
    ids = done()
    if level_id not in ids:
        ids.append(level_id)
    data["done"] = ids
    _save(data)
    return ids


def levels_for(lexicon, layout) -> list[dict]:
    """The levels with the keys that type each sentence on this layout."""
    from .devtools.keyscript import script_for

    return [{**asdict(lv), "keys": script_for(lv.type_text, lexicon, layout)} for lv in LEVELS]
