"""練習場: a guided tour of the IME in the settings page, its progress, and
the "practising" flag that keeps the IME from learning anything meanwhile.

Chapters walk through everything once (switch over, type, what the colours
mean and how to undo them, correction mode, symbols/voice); afterwards any
chapter can be replayed on its own. A *task* step is passed by typing in a
box with the real IME until it says the target; a *tip* step is a sentence
and a button.

Every sentence is made up for this page (never the user's own text — the
user asked for that, for privacy), and every task that shows a mistake is a
mistake the IME really makes with an empty dictionary: tests/test_practice.py
types each one, checks that it comes out as described, applies the step's
keys and checks the result. A step whose sentence the IME starts getting
right fails there, instead of becoming a step with nothing to fix.

The settings page shows the steps; the user types into a text box there
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
class Chapter:
    id: str
    title: str
    lead: str  # one sentence under the title


@dataclass(frozen=True)
class Step:
    id: str
    chapter: str
    title: str
    hook: str  # the one line that makes it click (HTML: <kbd>), shown big
    how: str  # what to do, short (HTML: <kbd>)
    kind: str = "task"  # task: type until the box says target | tip: read and press 知道了
    type_text: str = ""  # task: what to type the usual way (the keys come from it)
    keys: str = ""  # task: explicit key script instead (a deliberate typo, Tab, ::); {X} = a named key
    wrong: str = ""  # task: what the IME shows before the fix (tests); "" = nothing to check
    target: str = ""  # task: what the box must say at the end (trailing spaces ignored)
    fix: str = ""  # task: keys after typing, simulator syntax (tests); {T:字} types 字, {PICK:x} picks x
    pro: str = ""  # shown after passing: the "and there is more" line (HTML)
    note: str = ""  # task: what to type differently, when type_text is not the target


CHAPTERS: tuple[Chapter, ...] = (
    Chapter("start", "切過來", "先打一句，確認是順打在打字。"),
    Chapter("type", "直接打", "中文、英文、標點，一路打下去就好。"),
    Chapter("colors", "它替你改的，都看得到、改得回", "面板上只有四種顏色、四個意思。"),
    Chapter("fix", "修正模式", "<kbd>Esc</kbd> 之後鍵盤變成指令，字不會亂跑。"),
    Chapter("more", "還有這些", "符號、emoji、片語、語音。"),
)

STEPS: tuple[Step, ...] = (
    # ---------------------------------------------------------------- 切過來
    Step("hello", "start", "打第一句",
         "切到順打輸入法，打一句看看。",
         "按 <kbd>Win</kbd>+<kbd>空白</kbd> 選「順打輸入法」，在框裡打「你好」，<kbd>Enter</kbd>。",
         type_text="你好", target="你好",
         pro="系統匣的圖示：自＝中英自動、中＝純注音、英＝純英文。單按 <kbd>Shift</kbd> 就輪流切。"),
    # ---------------------------------------------------------------- 直接打
    Step("mixed", "type", "中英一起打",
         "英文不用切換，直接打。",
         "照平常打「我用vscode寫程式」，<kbd>Enter</kbd>。",
         type_text="我用vscode寫程式", target="我用vscode寫程式",
         pro="大寫縮寫、camelCase 也照出來。要連續打英文，<kbd>Caps Lock</kbd>，或單按 <kbd>Shift</kbd> 切到「英」。"),
    Step("reversed", "type", "打反了也認得",
         "ㄉㄜ˙ 打成 <kbd>k27</kbd>（反了）照樣是「的」。",
         "照這串按：<kbd>rup</kbd> <kbd>空白</kbd> <kbd>wu0</kbd> <kbd>k27</kbd>，<kbd>Enter</kbd>。",
         keys="rup wu0 k27", target="今天的",
         pro="聲調打早（<kbd>248</kbd> → 大）、漏打聲調也認得。它改過的地方，面板會標琥珀色。"),
    Step("punct", "type", "標點不用切",
         "<kbd>Ctrl</kbd>＋標點鍵就是中文標點；句讀一打，前面的句子自動送出。",
         "打「你好」，再按 <kbd>Ctrl</kbd>+<kbd>,</kbd>。",
         type_text="你好", fix="{C-,}", target="你好，",
         pro="<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>/</kbd> 是？，<kbd>Ctrl</kbd>+<kbd>[</kbd> <kbd>]</kbd> 是「」。每一格都能在「標點與符號」改。"),
    Step("tab", "type", "Tab 接下去",
         "提示列右邊出現的字，<kbd>Tab</kbd> 就接上。",
         "打「今天」（<kbd>rup</kbd> <kbd>空白</kbd> <kbd>wu0</kbd> <kbd>空白</kbd>），看到「的 Tab」按 <kbd>Tab</kbd>，<kbd>Enter</kbd>。",
         type_text="今天", wrong="今天", fix="{TAB}", target="今天的",
         pro="<kbd>Shift</kbd>+<kbd>Tab</kbd> 列出所有接法；<kbd>Ctrl</kbd>+<kbd>2</kbd>…<kbd>9</kbd> 直接接第幾個。"),
    # ---------------------------------------------------------------- 顏色
    Step("legend", "colors", "四種顏色",
         "面板上的顏色只有四個意思。",
         "<i class=\"p-dot\" style=\"background:var(--accent)\"></i>藍＝游標、選中的字　"
         "<i class=\"p-dot\" style=\"background:var(--ok)\"></i>綠＝你自己的詞　"
         "<i class=\"p-dot\" style=\"background:var(--plan)\"></i>琥珀＝輸入法替你改過　"
         "<i class=\"p-dot\" style=\"background:var(--warn)\"></i>紅＝被略過的鍵。看到琥珀或紅，<kbd>↓</kbd> 就能改回原樣。",
         kind="tip"),
    Step("undo-fix", "colors", "英文打錯會改好",
         "<kbd>wrold</kbd> 自動變 world，琥珀色小籤告訴你。",
         "打 <kbd>wrold</kbd> 加空白，看到「更正 wrold → world ↓」就按 <kbd>↓</kbd>，選 wrold（第 2 個），<kbd>Enter</kbd>。",
         keys="wrold ", wrong="world ", fix="{DOWN}{PICK:wrold}", target="wrold",
         pro="選了原樣它就記住，這個字以後不再改。teh → the、recieve → receive 也是同一套。"),
    Step("undo-drop", "colors", "略過的鍵救得回",
         "手滑多按的鍵會被略過（紅色）；真的要它，<kbd>↓</kbd> 一下就回來。",
         "打 <kbd>venv</kbd> 加空白——它會讀成 ven、說「略過 v」。按 <kbd>↓</kbd> 選 venv，<kbd>Enter</kbd>。",
         keys="venv ", wrong="ven ", fix="{DOWN}{PICK:venv}", target="venv",
         pro="常用的英文字按 <kbd>Ctrl</kbd>+<kbd>D</kbd> 加進詞庫，以後永遠照打。練習中不會動你的詞庫，所以這裡先不試。"),
    Step("ctrld", "colors", "Ctrl+D 記住這個字",
         "中文詞、英文字都一樣：打好之後按 <kbd>Ctrl</kbd>+<kbd>D</kbd>。",
         "朋友的名字修好了、專案的英文縮寫打完了，<kbd>Ctrl</kbd>+<kbd>D</kbd> 就進「我的詞庫」：下次排第一，也不會再被改。",
         kind="tip"),
    # ---------------------------------------------------------------- 修正模式
    Step("swap", "fix", "換一個字",
         "游標停在錯字上，<kbd>j</kbd> 換下一個同音字。",
         "打「你先走吧」（會變「八」）。<kbd>Esc</kbd>，游標就在「八」上，按 <kbd>j</kbd>，<kbd>Enter</kbd>。",
         type_text="你先走吧", wrong="你先走八", target="你先走吧", fix="{ESC}j",
         pro="<kbd>k</kbd> 往回換。只換這一個字，旁邊的字不會跟著變。"),
    Step("list", "fix", "從選字窗挑",
         "同音字多的時候，<kbd>↓</kbd> 打開選字窗按數字。",
         "打「記得帶雨傘」（會變「代」）。<kbd>Esc</kbd>，<kbd>←</kbd> 兩下到「代」，<kbd>↓</kbd>，按「帶」前面的數字，<kbd>Enter</kbd>。",
         type_text="記得帶雨傘", wrong="記得代雨傘", target="記得帶雨傘",
         fix="{ESC}{LEFT}{LEFT}{DOWN}{PICK:帶}",
         pro="選字窗分組上色：我的詞庫、學過、詞庫…<kbd>Tab</kbd> 在分組間跳，<kbd>→</kbd> 多開一欄。"),
    Step("word", "fix", "換一整個詞",
         "<kbd>↓</kbd> 最上面是從這裡開始的詞，一次換一整個。",
         "打「他的公式很複雜」（會變「公視」）。<kbd>Esc</kbd>，移到「公」，<kbd>↓</kbd> 選「公式」，<kbd>Enter</kbd>。",
         type_text="他的公式很複雜", wrong="他的公視很複雜", target="他的公式很複雜",
         fix="{ESC}{LEFT}{LEFT}{LEFT}{LEFT}{DOWN}{PICK:公式}",
         pro="選過的詞會記住：下次同一句就對了。"),
    Step("english", "fix", "英文旁邊的字",
         "英文整個字算一格，<kbd>←</kbd> 一下就跨過去。",
         "打「明天見bye」（會變「建」）。<kbd>Esc</kbd> 後游標在 bye 上，<kbd>←</kbd> 一下到「建」，<kbd>j</kbd>，<kbd>Enter</kbd>。",
         type_text="明天見bye", wrong="明天建bye", target="明天見bye", fix="{ESC}{LEFT}j",
         pro="要動英文字裡的單一字母，<kbd>v</kbd> 切到「按鍵」檢視。"),
    Step("tone", "fix", "打錯聲調",
         "聲調錯了，直接按對的聲調鍵，不用重打。",
         "照打「我想買房子」（故意的，會變「防」）。<kbd>Esc</kbd>，移到「買」按第四聲 <kbd>4</kbd> 變「賣」；<kbd>→</kbd> 到「防」按 <kbd>j</kbd>，<kbd>Enter</kbd>。",
         type_text="我想買房子", wrong="我想買防子", target="我想賣房子",
         fix="{ESC}{LEFT}{LEFT}{T:ˋ}{RIGHT}j", note="目標是「賣」，故意先打「買」",
         pro="空白、<kbd>6</kbd> <kbd>3</kbd> <kbd>4</kbd> <kbd>7</kbd> 五個聲調鍵都行。"),
    Step("retype", "fix", "整個音打錯",
         "<kbd>r</kbd> 把這個字的注音清掉重打，打完自動回來。",
         "照打「今天很樂」。<kbd>Esc</kbd>（游標在「樂」），按 <kbd>r</kbd>，重打「熱」ㄖㄜˋ，<kbd>Enter</kbd>。",
         type_text="今天很樂", wrong="今天很樂", target="今天很熱", fix="{ESC}r{T:熱}",
         note="目標是「熱」，故意先打「樂」",
         pro="重打到一半後悔，<kbd>Esc</kbd> 原字放回去。"),
    Step("dropped", "fix", "救回被略過的鍵",
         "被略過的鍵，在修正模式裡也救得回。",
         "打「e化的流程」（e 會被略過，變「畫」）。<kbd>Esc</kbd>，移到「畫」——面板說「略過了 e」——<kbd>↓</kbd> 選 e，<kbd>→</kbd> 回到「畫」按 <kbd>j</kbd>，<kbd>Enter</kbd>。",
         type_text="e化的流程", wrong="畫的流程", target="e化的流程",
         fix="{ESC}{LEFT}{LEFT}{LEFT}{DOWN}{PICK:e}{RIGHT}j",
         pro="游標停在被略過的鍵旁邊時，面板下方會直接說怎麼救。"),
    Step("extra", "fix", "刪掉多打的鍵",
         "多打的鍵，<kbd>x</kbd> 刪掉。",
         "打「我好」再多打一個 <kbd>q</kbd>。<kbd>Esc</kbd>（游標在 q 上），按 <kbd>x</kbd>，<kbd>Enter</kbd>。",
         type_text="我好q", wrong="我好q", target="我好", fix="{ESC}x", note="最後故意多打一個 q",
         pro="<kbd>x</kbd> 刪的是反白的那一格：英文是整個字。<kbd>u</kbd> 復原。"),
    Step("regroup", "fix", "英文吃掉了下一個字",
         "英文和中文黏在一起時，<kbd>↓</kbd> 直接列出其他分法。",
         "打「這個game你玩過嗎」（game 後面沒空白，會變 games以）。<kbd>Esc</kbd>，移到「以」，<kbd>↓</kbd> 最上面「重新分組」選 game｜你，<kbd>Enter</kbd>。",
         type_text="這個game你玩過嗎", wrong="這個games以玩過嗎", target="這個game你玩過嗎",
         fix="{ESC}{LEFT}{LEFT}{LEFT}{DOWN}{PICK:game｜你}",
         pro="游標移到這種地方時，面板會直接提示最好的那個分法。"),
    Step("number", "fix", "數字吃掉了注音",
         "數字鍵和注音鍵長得一樣，<kbd>↓</kbd> 一樣切得開。",
         "打「排行榜前10大」（會變 10284）。<kbd>Esc</kbd>，<kbd>↓</kbd> 選 10｜大，<kbd>Enter</kbd>。",
         type_text="排行榜前10大", wrong="排行榜前10284", target="排行榜前10大", fix="{ESC}{DOWN}{PICK:10｜大}",
         pro="數字後面打個空白再接注音，就不會黏在一起。"),
    Step("edge", "fix", "自己推分界",
         "想自己決定切在哪：<kbd>Shift</kbd>+<kbd>←</kbd> <kbd>→</kbd>。",
         "同一句「排行榜前10大」。<kbd>Esc</kbd>，<kbd>Shift</kbd>+<kbd>←</kbd> 把數字後面的分界往左推，看琥珀色直線，推到 10｜大 就 <kbd>Enter</kbd>。",
         type_text="排行榜前10大", wrong="排行榜前10284", target="排行榜前10大", fix="{ESC}{S-LEFT}{S-LEFT}{S-LEFT}",
         pro="規則只有一條：方向鍵移游標，加 <kbd>Shift</kbd> 就是移分界。"),
    Step("combo", "fix", "一句兩個錯",
         "兩個錯一起修；按錯了 <kbd>u</kbd> 復原。",
         "打「OK啦你先走吧」（會變「拉」「八」）。<kbd>Esc</kbd> 在「八」按 <kbd>j</kbd>，往左到「拉」再 <kbd>j</kbd>，<kbd>Enter</kbd>。",
         type_text="OK啦你先走吧", wrong="OK拉你先走八", target="OK啦你先走吧",
         fix="{ESC}j{LEFT}{LEFT}{LEFT}{LEFT}j",
         pro="<kbd>R</kbd> 重新判定一段、<kbd>D</kbd><kbd>D</kbd> 清空整段——都在面板說明列的第二行。"),
    # ---------------------------------------------------------------- 還有這些
    Step("symbol", "more", "符號面板",
         "連打兩個冒號 <kbd>::</kbd>，符號面板就開了。",
         "打 <kbd>:</kbd><kbd>:</kbd>（Shift+; 兩下），<kbd>Tab</kbd> 換到括號那一頁，按 <kbd>1</kbd>。",
         keys="::{TAB}1", target="「",
         pro="每一頁都一樣：<kbd>↓</kbd> 同一欄往下、<kbd>→</kbd> 下一欄、數字選。「我的符號」可以放自己常用的。"),
    Step("emoji", "more", "emoji 用搜的",
         "三個冒號接關鍵字，emoji 即時篩選。",
         "打 <kbd>:::</kbd> 接 <kbd>star</kbd>，按 <kbd>1</kbd>。",
         keys=":::star1", target="★",
         pro="star、heart、星座、動物……中英文關鍵字都行。"),
    Step("snippets", "more", "片語",
         "常打的整段話存成片語，<kbd>;;</kbd> 叫出來。",
         "到「片語與顏文字」存一則（例如 addr＝你的地址），之後打 <kbd>;;addr</kbd>，先預覽再 <kbd>Enter</kbd>。顏文字也在那一頁。",
         kind="tip"),
    Step("voice", "more", "用說的",
         "按住右 <kbd>Ctrl</kbd> 說話，放開就打在游標位置。",
         "第一次要到「語音輸入」裝語音元件。辨識全在這台電腦上，聲音不會上傳。",
         kind="tip"),
    Step("modes", "more", "三種模式",
         "單按 <kbd>Shift</kbd> 在模式之間輪流。",
         "中英自動是預設；要一直打英文就切到「英」，純注音切到「中」。哪些模式要輪流，在「一般」設定。",
         kind="tip"),
)

STEP_IDS = frozenset(s.id for s in STEPS)


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


def mark_done(step_id: str) -> list[str]:
    if step_id not in STEP_IDS:
        return done()
    data = _load()
    ids = done()
    if step_id not in ids:
        ids.append(step_id)
    data["done"] = ids
    _save(data)
    return ids


def reset() -> list[str]:
    data = _load()
    data["done"] = []
    _save(data)
    return []


def step_keys(step: Step, lexicon, layout) -> str:
    """The keys that type the step's sentence on this layout."""
    if step.keys:
        return step.keys
    from .devtools.keyscript import script_for

    return script_for(step.type_text, lexicon, layout)


def chapters_for(lexicon, layout) -> list[dict]:
    """The tour, with the keys that type each sentence on this layout.
    ``show_keys`` is off where the script has named keys ({TAB}): the
    instruction says what to press."""
    out = []
    for ch in CHAPTERS:
        steps = []
        for st in STEPS:
            if st.chapter != ch.id:
                continue
            keys = step_keys(st, lexicon, layout) if st.kind == "task" else ""
            steps.append({**asdict(st), "keys": keys, "show_keys": bool(keys) and "{" not in keys})
        out.append({**asdict(ch), "steps": steps})
    return out
