"""Per-input-context state machine.

The session owns the uncommitted *key buffer*. Everything shown in the
composition is derived from it by the decoder, so editing is always done on
raw keys and the interpretation can change as more context arrives.

UX (mode B agreed in Phase 2): looks like 華碩智慧輸入法 — typed letters show
inline, the zhuyin of an unfinished syllable is shown as a hint, a tone key
turns it into Chinese — but text stays in the composition (underlined) until
Enter / clause punctuation / overflow, so earlier characters can still be
fixed with the candidate window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from ..config import Config
from . import bopomofo
from .decoder import (
    CANGJIE_RADICALS, CLAUSE_PUNCT, FULLWIDTH_PUNCT, PLAIN_PUNCT, PUNCT_ALTERNATIVES, PUNCT_VARIANTS,
    Decoder, Decoding, Key, Kind,
    Segment,
)
from .keys import (
    MODIFIER_VKS, SCAN_LSHIFT, SCAN_RSHIFT, VK_BACK, VK_DELETE, VK_DOWN, VK_END, VK_ESCAPE,
    VK_HOME, VK_LEFT, VK_NEXT, VK_NUMPAD0, VK_NUMPAD9, VK_OEM_1, VK_OEM_2, VK_OEM_4, VK_OEM_6,
    VK_OEM_7, VK_OEM_COMMA, VK_OEM_MINUS, VK_OEM_PERIOD, VK_PRIOR, VK_RETURN, VK_RIGHT, VK_SHIFT,
    VK_SPACE, VK_TAB, VK_UP, VK_MENU, VK_PACKET, VK_CONTROL, KeyInput,
)
from .layouts import Layout
from .lexicon import Lexicon
from .userdict import UserDict
from .correction import CorrectionMixin
from .panel import (
    CandidatePanel, DecodePanel, HintPanel, SmartPanel, candidate_panel, decode_panel, smart_panel,
)
from .punct import ctrl_output
from .symbols import CATEGORIES, LIST_TABS, NEWLINE_SYMBOL, TABS, SymbolPanel

VK_D = 0x44
VK_Y = 0x59
VK_Z = 0x5A
SHIFT_TAP_SECONDS = 0.5
# A right-Ctrl tap must stay shorter than voice input's shortest hold (0.35 s),
# so the two never both happen.
CTRL_TAP_SECONDS = 0.3
SELECTION_DIGITS = "123456789"
SINGLE_CHAR_SUGGEST_MARGIN = 1.5  # stricter autocomplete threshold for 1-char context
MAX_SUGGESTIONS = 18  # continuations kept (the hint box shows suggestion_count; Shift+Tab lists all)

# Keys we consume while composing even though they produce no character.
_COMPOSING_NAV = frozenset(
    {VK_BACK, VK_DELETE, VK_RETURN, VK_ESCAPE, VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN,
     VK_HOME, VK_END, VK_TAB}
)
# Volume / media / browser keys: they do not touch the document, so they may
# reach the app without ending the composition.
_MEDIA_VKS = frozenset(range(0xA6, 0xB8))


class Mode(str, Enum):
    AUTO = "auto"  # 中英自動：解碼器自行判斷中文或英文（中文用設定的輸入法；預設）
    CHINESE = "chinese"  # 純注音：每個鍵都是注音（數字請用數字鍵盤）
    ENGLISH = "english"  # 純英文：按鍵直接交給應用程式
    PINYIN = "pinyin"  # 純拼音
    CANGJIE = "cangjie"  # 純倉頡（五代）

    @property
    def label(self) -> str:
        return {"auto": "中英自動", "chinese": "純注音", "english": "純英文",
                "pinyin": "純拼音", "cangjie": "純倉頡"}[self.value]


SCHEME_LABEL = {"zhuyin": "注音", "pinyin": "拼音", "cangjie": "倉頡"}


# Candidate groups, in the order the window lists them: your own words
# first, then what you chose before, then the dictionary, then the other
# ways to read the keys (user feedback #6-2: "先從自訂群組匹配，然後常用，
# 最後推薦"). The panel colours each group (smartime.ui.theme).
GROUP_ORDER = ("我的詞庫", "學過", "詞庫", "英文", "數字", "標點", "其他讀法", "原始按鍵", "略過的鍵",
               "長句", "也許是", "接續", "符號")
MAX_COLUMNS = 4  # multi-column candidate window: pages shown side by side


@dataclass
class Candidate:
    text: str
    pin: Segment | None
    annotation: str = ""
    symbol: str = ""  # symbol panel entry
    suggestion: "Suggestion | None" = None  # continuation list entry
    group: str = ""  # see GROUP_ORDER
    preview: str = ""  # 片語: the whole text, shown under the list before it is typed
    snippet_id: int | None = None


@dataclass
class CandidateList:
    """The candidate window's state. ``index`` points into ``shown`` (the
    items left after the group filter). Single-column mode turns pages with
    ←/→; multi-column mode opens the next page as another column with →
    and folds back to one column with ← on the first."""

    items: list[Candidate]
    page_size: int
    index: int = 0
    title: str = ""  # shown in the message window (symbol panel category)
    palette: int | None = None  # symbol panel: current category index
    multi: bool = False  # → opens columns instead of turning pages
    snippet_at: int | None = None  # opened by ;; : the trigger's first key (letters after it filter)
    trigger_at: int | None = None  # text trigger (;; or ::): its first key, removed when something is picked
    query: str = ""
    filter: str = ""  # "" = every group
    columns: int = 1  # pages shown side by side
    first_page: int = 0  # leftmost page shown

    @property
    def shown(self) -> list[Candidate]:
        return [c for c in self.items if not self.filter or c.group == self.filter]

    @property
    def current(self) -> Candidate:
        return self.shown[self.index]

    @property
    def page(self) -> int:
        return self.index // self.page_size

    @property
    def pages(self) -> int:
        return max(1, (len(self.shown) + self.page_size - 1) // self.page_size)

    def page_items(self, page: int | None = None) -> list[Candidate]:
        start = (self.page if page is None else page) * self.page_size
        return self.shown[start:start + self.page_size]

    def groups(self) -> list[str]:
        """Groups present, in display order (the filter cycles through them)."""
        return list(dict.fromkeys(c.group for c in self.items if c.group))

    def move(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.shown)
        self._keep_visible()

    def move_page(self, delta: int) -> None:
        page = (self.page + delta) % self.pages
        self.index = page * self.page_size
        self.first_page, self.columns = page, 1

    def move_column(self, delta: int, expand: str = "grow") -> None:
        """← → walk the columns, the way 微軟新注音's candidate window does.

        The window starts as one tall list of 1–9. → opens the next page
        beside it as another column and puts the cursor on the same row
        there, so more and more choices are on screen at once. ← walks back;
        on the first column it folds the window back into the single list.

        At the right-hand edge, ``expand`` decides what → does: "grow" adds
        one more column (then scrolls a column at a time), "page" replaces
        the whole set with the next one and starts again at the left.
        """
        row = self.index % self.page_size
        last_visible = self.first_page + self.columns - 1
        if delta < 0:
            if self.page > self.first_page:
                target = self.page - 1
            elif self.first_page > 0:
                # At the left edge of a window that has already slid forward
                # (→ scrolled past MAX_COLUMNS at some point): slide it back
                # one column first, same width, the same way → slid it
                # forward — column[i] becomes column[i-1], not a collapse.
                # Reported: pressing ← here closed the whole window and
                # reopened at column 0 instead of revealing one earlier
                # column.
                self.first_page -= 1
                target = self.first_page
            elif self.columns > 1:
                self.columns = 1  # nothing earlier: fold back into one list
                return
            else:
                return
        else:
            target = self.page + 1
            if target >= self.pages:
                return
            if target > last_visible:
                if expand == "page":
                    self.first_page = target
                    self.columns = min(MAX_COLUMNS, self.pages - self.first_page)
                elif self.columns < MAX_COLUMNS:
                    self.columns += 1
                else:
                    self.first_page += 1
        self.index = min(target * self.page_size + row, len(self.shown) - 1)
        self.first_page = min(self.first_page, self.page)
        self.columns = max(self.columns, self.page - self.first_page + 1)

    def cycle_filter(self, delta: int) -> None:
        options = [""] + self.groups()
        if len(options) <= 2:
            return  # a single group: nothing to filter
        self.filter = options[(options.index(self.filter) + delta) % len(options)]
        self.index = self.first_page = 0
        self.columns = 1

    def _keep_visible(self, grow: bool = False) -> None:
        page = self.page
        if page < self.first_page:
            self.first_page = page
        elif page >= self.first_page + self.columns:
            if grow and self.multi and page - self.first_page + 1 <= MAX_COLUMNS:
                self.columns = page - self.first_page + 1
            else:
                self.first_page = page - self.columns + 1


@dataclass
class Suggestion:
    text: str  # what Tab will append
    pin: Segment  # the full phrase pinned after accepting
    keys: list[Key]  # keys appended to the buffer


@dataclass
class Smart:
    """超智慧推薦 (experimental): chains of what may come next, and
    homophones of the last characters. ``stale`` while a syllable is being
    typed: still shown (it does not flicker away) but not pickable."""

    chains: list[Suggestion]
    fixes: list[Candidate]
    stale: bool = False
    context: str = ""  # the characters the chains continue from


@dataclass
class View:
    """Everything a frontend needs to render after an event."""

    composition: str = ""
    cursor: int = 0
    commit: str = ""
    candidates: list[str] | None = None
    candidate_notes: list[str] | None = None  # e.g. 朋友, 學過, 原始按鍵
    candidate_index: int = 0
    hint: str = ""
    suggestion: str = ""
    suggestions: list[str] = field(default_factory=list)  # first = what Tab takes
    candidate_title: str = ""
    notice: str = ""  # one-off feedback ("已加入詞庫：…"), shown once
    mode: Mode = Mode.AUTO
    correcting: bool = False  # correction mode (Esc)
    layer: str = "text"  # its view: text | zhuyin | keys
    panel: "DecodePanel | None" = None  # decode panel to draw (see engine.panel), if wanted
    candidate_panel: "CandidatePanel | None" = None  # the candidate window as a panel
    smart_panel: "SmartPanel | None" = None  # 超智慧推薦 (experimental)
    hint_panel: "HintPanel | None" = None  # the strip under the text (see engine.panel)


@dataclass
class Engine:
    """Shared resources for all sessions in the process."""

    lexicon: Lexicon
    layout: Layout
    decoder: Decoder
    config: Config
    config_path: Path | None = None  # reloaded when the file changes
    symbols: SymbolPanel = field(default_factory=lambda: SymbolPanel(None))
    _config_mtime: float = 0.0

    @property
    def user(self) -> UserDict | None:
        return self.lexicon.user

    def refresh(self) -> None:
        """Pick up changes made by the settings app (config file, user
        dictionary). Cheap enough to call on every key."""
        self.lexicon.refresh()
        if self.config_path is None:
            return
        try:
            mtime = self.config_path.stat().st_mtime
        except OSError:
            return
        if mtime != self._config_mtime:
            if self._config_mtime:  # not the first check
                self.config = Config.load(self.config_path)
                self.decoder.apply_config(self.config)
                self.layout = self.decoder.layout  # 大千 / 倚天 switch
            self._config_mtime = mtime


class Session(CorrectionMixin):
    def __init__(self, engine: Engine):
        self.engine = engine
        self.mode = Mode(self.cfg.start_mode)
        if not self._available(self.mode):
            self.mode = Mode.AUTO
        # The Chinese-side mode a Shift tap returns to from English.
        self.chinese_mode = self.mode if self.mode is not Mode.ENGLISH else Mode.AUTO
        self.keys: list[Key] = []
        self.pins: list[Segment] = []
        self.cursor = 0  # position in self.keys
        self.decoding = Decoding((), 0.0)
        self.cand: CandidateList | None = None
        self.suggestion: Suggestion | None = None
        self.suggestions: list[Suggestion] = []
        self._commit = ""
        self._notice = ""
        self._learned_here: list[tuple[str, str]] = []  # (phrase, reading) this composition invented
        self._text_here = ""  # everything this composition has put on screen so far
        self._shift_down_at: float | None = None
        self._palette_down_at: float | None = None  # the symbol-panel key went down (alone) at
        self._shift_scan = 0
        # Undo inside the composition (Ctrl+Z / Ctrl+Y, and u in correction
        # mode): (keys, pins, cursor) before each edit.
        self._history: list[tuple[list[Key], list[Segment], int]] = []
        self._redo: list[tuple[list[Key], list[Segment], int]] = []
        self._typing_run = False  # the last step is a run of typing that may still grow
        self.hand_back: KeyInput | None = None  # see key_down / take_hand_back
        self.smart: Smart | None = None  # 超智慧推薦 (experimental)
        self._init_correction()

    # ================================================================ API
    @property
    def cfg(self) -> Config:
        # Always the engine's current config (it is reloaded when the
        # settings app saves).
        return self.engine.config

    @property
    def composing(self) -> bool:
        return bool(self.keys)

    def view(self) -> View:
        units = self.decoding.units()
        cursor_chars = sum(1 for a, b, _, _ in units if b <= self.cursor)
        v = View(
            composition=self.decoding.text,
            cursor=cursor_chars,
            commit=self._commit,
            mode=self.mode,
        )
        self._commit = ""
        v.notice, self._notice = self._notice, ""
        if self.correcting:
            v.composition, v.cursor = self._correction_view()
            v.correcting, v.layer = True, self.layer
        # 瘋狂模式 guesses a lot: always show what each key became
        wanted = "always" if self.cfg.crazy_mode and self.scheme == "zhuyin" else self.cfg.panel_decode
        if self.keys and (wanted == "always" or (wanted == "correction" and self.correcting)):
            v.panel = decode_panel(self)
        if self.cfg.smart_suggest and self.keys and not self.correcting and self.cand is None:
            v.smart_panel = smart_panel(self)
        if self.cand is not None:
            page = self.cand.page_items()
            v.candidates = [c.text for c in page]
            v.candidate_notes = [c.annotation for c in page]
            v.candidate_index = self.cand.index % self.cand.page_size
            v.candidate_title = self.cand.title
            if not v.candidate_title and "學過" in v.candidate_notes:
                v.candidate_title = "選字框裡按 Delete 可忘記「學過」的詞"
            v.candidate_panel = candidate_panel(self)
        elif self.correcting:
            v.hint = self._correction_hint()
        else:
            v.hint = self._hint()
            if not v.hint and self.suggestion is not None:
                v.suggestion = self.suggestion.text
                v.suggestions = [x.text for x in self.suggestions[:self.cfg.suggestion_count]]
        v.hint_panel = self._hint_panel(v)
        # One-off feedback used to live in PIME's message window; now that we
        # draw everything ourselves it has to ride on whichever panel is up,
        # or it would never be seen.
        if v.notice:
            if v.candidate_panel is not None:
                v.candidate_panel.notice = v.notice
            elif v.panel is not None:
                v.panel.notice = v.notice
        return v

    def _hint_panel(self, v: View) -> HintPanel | None:
        """The strip we draw ourselves instead of PIME's yellow tooltip."""
        if self.cand is not None or self.correcting:
            return None  # those panels say everything already
        reading, becomes, dropped, info = self._hint_parts()
        panel = HintPanel(reading=reading, becomes=becomes, dropped=dropped, info=info,
                          suggestion=v.suggestion, others=list(v.suggestions[1:]),
                          more=len(self.suggestions) > len(v.suggestions), notice=v.notice,
                          composing=bool(self.keys) and self.cfg.composing_indicator)
        return panel or None

    def filter_key_down(self, key: KeyInput) -> bool:
        if key.vk == VK_SHIFT:
            self._shift_down_at = time.monotonic()
            self._palette_down_at = None
            self._shift_scan = key.scan
        else:
            self._shift_down_at = None
            # a lone tap of the symbol-panel key opens it; any other key in
            # between (Ctrl+C, Alt+Tab, AltGr+key) makes it a shortcut instead.
            # Held keys repeat their key-down: keep the first time.
            if self._is_palette_key(key):
                if self._palette_down_at is None:
                    self._palette_down_at = time.monotonic()
            else:
                self._palette_down_at = None
        return self._wants(key)

    def key_down(self, key: KeyInput) -> bool:
        if not self._wants(key):
            return False
        if self.cand is not None:
            if self._candidate_key(key):
                return True
            self.cand = None  # any other key closes the window and is typed
        if self.correcting:
            if self._correction_key(key):
                return True
            self.exit_correction()  # e.g. Ctrl+symbol: back to typing
        if self._for_the_app(key):
            # Ctrl+V, Ctrl+S, Ctrl+Enter, F5, text from another program …:
            # the composition is committed first, then the key goes on to
            # the app, so a paste lands after the text instead of inside the
            # composition. Returning False lets the key through in TSF apps;
            # apps on the IMM32 compatibility layer (classic EDIT, Scintilla,
            # Qt …) have already lost it by then, so the frontend may take
            # ``hand_back`` and send the key again itself.
            self.commit_all()
            self.hand_back = key
            return False
        return self._edit_key(key)

    def take_hand_back(self) -> KeyInput | None:
        """The key the last key_down committed for and meant for the app."""
        key, self.hand_back = self.hand_back, None
        return key

    def _for_the_app(self, key: KeyInput) -> bool:
        """A key we do not handle that would act on the document while a
        composition is open."""
        if not self.composing or key.vk in MODIFIER_VKS or key.vk in _MEDIA_VKS:
            return False
        if key.vk == VK_PACKET:
            return True
        if self._suggestion_digit(key) is not None:
            return False  # Ctrl+2 takes a continuation; it is ours
        if key.ctrl or key.alt:
            return self._ctrl_punct(key) is None and not (key.ctrl and not key.alt and key.vk in (VK_D, VK_Y, VK_Z))
        if key.vk == VK_RETURN and self._newline_modifier(key):
            # The configured line-break Enter: send the text first, then let
            # the key through so the application makes the break itself.
            return True
        return not key.printable and key.vk not in _COMPOSING_NAV

    def filter_key_up(self, key: KeyInput) -> bool:
        if self._is_palette_key(key) and not self._is_palette_tap(key):
            self._palette_down_at = None  # held (voice input) or a shortcut: the next press starts afresh
        return self._is_shift_tap(key) or self._is_palette_tap(key)

    def key_up(self, key: KeyInput) -> bool:
        if self._is_palette_tap(key):
            self._palette_down_at = None
            self.toggle_palette()
            # Alt's key-up is taken (or the app would open its menu bar);
            # Ctrl's goes on, so the app sees Ctrl released
            return self.cfg.palette_hotkey != "rctrl"
        if not self._is_shift_tap(key):
            return False
        self._shift_down_at = None
        self.toggle_mode()
        return True

    def toggle_mode(self) -> None:
        """Shift tap. Default (``shift_cycle = "three"``): the modes turned on
        in ``mode_cycle``, in turn (自動 -> 純注音 -> 純英文 ...). With "two":
        English <-> the Chinese-side mode used last."""
        if self.cfg.shift_cycle == "three":
            order = self.cycle_modes()
            nxt = order[(order.index(self.mode) + 1) % len(order)] if self.mode in order else order[0]
            self.set_mode(nxt)
        else:
            self.set_mode(self.chinese_mode if self.mode is Mode.ENGLISH else Mode.ENGLISH)

    def cycle_modes(self) -> list[Mode]:
        modes = [Mode(m) for m in self.cfg.mode_cycle.split(",") if m]
        return [m for m in modes if self._available(m)] or [Mode.AUTO, Mode.ENGLISH]

    def _available(self, mode: Mode) -> bool:
        """Pinyin/Cangjie need data from a newer system lexicon."""
        lex = self.engine.lexicon
        if mode is Mode.PINYIN:
            return lex.has_pinyin
        if mode is Mode.CANGJIE:
            return lex.has_cangjie
        return True

    @property
    def scheme(self) -> str:
        """How Chinese is typed right now: zhuyin, pinyin or cangjie."""
        if self.mode is Mode.PINYIN:
            return "pinyin"
        if self.mode is Mode.CANGJIE:
            return "cangjie"
        if self.mode is Mode.CHINESE:
            return "zhuyin"
        scheme = self.cfg.chinese_scheme
        if (scheme == "pinyin" and not self.engine.lexicon.has_pinyin) or (
                scheme == "cangjie" and not self.engine.lexicon.has_cangjie):
            return "zhuyin"
        return scheme

    def mode_label(self) -> str:
        """For the tray: 中英自動 says which Chinese it mixes in."""
        if self.mode is Mode.AUTO and self.scheme != "zhuyin":
            return f"中英自動（{SCHEME_LABEL[self.scheme]}）"
        return self.mode.label

    def set_mode(self, mode: Mode) -> None:
        self.commit_all()
        self.mode = mode
        if mode is not Mode.ENGLISH:
            self.chinese_mode = mode

    def commit_all(self) -> None:
        if self.correcting:
            self.exit_correction()
        self.cand = None
        if self.keys:
            self._commit += self.decoding.text
            self._text_here += self.decoding.text
        self._prune_learned()
        self._reset_buffer()

    def _prune_learned(self) -> None:
        """Take back the words this composition invented and then wrote over.

        A correction is remembered together with a neighbour, so that the
        same sentence comes out right next time. Fixing several characters
        one after another therefore leaves a trail of pairs built around
        characters that are no longer there: 彩但 on the way to 彩蛋, 蛋模 on
        the way to 蛋糕. None of them is a word anybody meant. Once the
        sentence is settled, whatever is not in it goes.
        """
        user = self.engine.user
        if user is None or not self._learned_here:
            return
        text, stale = self._text_here, False
        for phrase, reading in self._learned_here:
            if phrase not in text and user.unlearn_fresh(phrase, reading):
                stale = True
        self._learned_here = []
        if stale:
            self.engine.lexicon.invalidate()

    def reset(self) -> None:
        """Composition was terminated by the app (focus change, click, ...)."""
        self.cand = None
        self._text_here += self.decoding.text  # it stayed in the document
        self._prune_learned()
        self._reset_buffer()

    # ========================================================= key routing
    def _ctrl_punct(self, key: KeyInput) -> str | None:
        if not (key.ctrl and not key.alt and self.cfg.ctrl_punctuation and self.mode is not Mode.ENGLISH):
            return None
        return ctrl_output(self.cfg, key.vk, key.shift)

    def _wants(self, key: KeyInput) -> bool:
        if key.vk in MODIFIER_VKS:
            return False
        if key.vk == VK_PACKET:
            # text typed by a program (our voice input, password managers):
            # already final, never zhuyin. Only taken to commit first.
            return self.composing
        if self.cand is not None:
            return True
        if self._ctrl_punct(key) is not None:
            return True
        if self.composing and key.ctrl and not key.alt and key.vk in (VK_D, VK_Y, VK_Z):
            return True  # add the composition to my dictionary / undo / redo
        if self._suggestion_digit(key) is not None:
            return True  # Ctrl+2 takes the second continuation
        if self._for_the_app(key):
            return True  # commit, then pass it on (key_down returns False)
        if key.ctrl or key.alt:
            return False
        if self.mode is Mode.ENGLISH:
            return False
        if not self.composing:
            if not key.printable or key.char == " " or key.numpad:
                return False
            if key.caps and key.char.isalpha():
                return False  # Caps Lock = typing English capitals
            return True
        return key.vk in _COMPOSING_NAV or key.printable

    def _is_shift_tap(self, key: KeyInput) -> bool:
        if key.vk != VK_SHIFT or self._shift_down_at is None:
            return False
        if time.monotonic() - self._shift_down_at > SHIFT_TAP_SECONDS:
            return False
        which = self.cfg.toggle_shift
        if which == "none":
            return False
        if which == "left" and self._shift_scan not in (SCAN_LSHIFT, 0):
            return False
        if which == "right" and self._shift_scan not in (SCAN_RSHIFT, 0):
            return False
        return True

    def _suggestion_digit(self, key: KeyInput) -> int | None:
        """Index into ``self.suggestions`` for Ctrl+2 … Ctrl+9, when there is
        a continuation to take.

        Tab takes the first one; the rest were on screen with no way to reach
        them, because while composing the digit keys are zhuyin (reported:
        「數字鍵似乎會變成打字，不然你的推薦字都不能用」). Ctrl+digit was
        going straight to the application and is free here.

        Deliberately *not* ``key.digit``: that property also reads the
        numeric keypad's navigation keys as digits when NumLock is off
        (VK_LEFT -> "4" and so on), which exists only so a candidate window
        can be driven from that keypad. Reusing it here would have hijacked
        a real Ctrl+Left/Ctrl+Home/… typed on the keypad with NumLock off —
        found because the *test harness* happened to reproduce the same
        VK/extended combination for the dedicated arrow block, which pointed
        at the real version of this bug.
        """
        if not (key.ctrl and not key.alt and not key.shift) or not self.cfg.suggestion_ctrl_digits:
            return None
        if self.cand is not None or self.correcting or not self.suggestions:
            return None
        if len(key.char) == 1 and key.char in "123456789":
            digit = key.char
        elif VK_NUMPAD0 <= key.vk <= VK_NUMPAD9:
            digit = chr(ord("0") + key.vk - VK_NUMPAD0)
        else:
            return None
        if digit == "1":
            return None
        i = int(digit) - 1
        return i if i < min(len(self.suggestions), self.cfg.suggestion_count) else None

    def _edit_key(self, key: KeyInput) -> bool:
        vk = key.vk
        i = self._suggestion_digit(key)
        if i is not None:
            self._accept_suggestion(self.suggestions[i])
            return True
        punct = self._ctrl_punct(key)
        if punct is not None:
            # Inserted as a key whose character *is* the punctuation, so it
            # flows through the decoder (and clause punctuation commits).
            self._insert(Key(punct))
            return True
        if key.ctrl and vk == VK_D:
            self._add_composition_to_dict()
            return True
        if key.ctrl and vk in (VK_Y, VK_Z):
            # undo / redo inside the composition (Ctrl+Shift+Z = redo too)
            self.redo() if (vk == VK_Y or key.shift) else self.undo()
            return True
        if vk == VK_TAB and key.shift:
            self._open_continuations()
            return True
        if vk == VK_RETURN:
            self.commit_all()
        elif vk == VK_ESCAPE:
            if self.cfg.correction_mode:
                self.enter_correction()  # a second Esc (in correction mode) clears
            else:
                self._reset_buffer()
        elif vk == VK_BACK:
            self._delete_unit(before=True)
        elif vk == VK_DELETE:
            self._delete_unit(before=False)
        elif vk == VK_LEFT:
            self._move_unit(-1)
        elif vk == VK_RIGHT:
            self._move_unit(+1)
        elif vk == VK_HOME:
            self._typing_run = False
            self.cursor = 0
            self._refresh()
        elif vk == VK_END:
            self._typing_run = False
            self.cursor = len(self.keys)
            self._refresh()
        elif vk in (VK_UP, VK_DOWN):
            self._open_candidates()
        elif vk == VK_TAB:
            if self.suggestion is not None:
                self._accept_suggestion(self.suggestion)
            else:
                self.commit_all()
        elif key.printable:
            self._insert(Key(key.char, key.numpad))
        else:
            return False
        return True

    # ============================================================ undo
    def _checkpoint(self, typing: bool = False) -> None:
        """Remember the buffer before an edit. Typing is undone a word at a
        time: consecutive keys share one step until a tone key, a space or
        punctuation completes something."""
        if typing and self._typing_run:
            return
        self._history.append((list(self.keys), list(self.pins), self.cursor))
        del self._history[:-100]
        self._redo.clear()
        self._typing_run = typing

    def undo(self) -> bool:
        return self._step(self._history, self._redo, "沒有可以復原的動作")

    def redo(self) -> bool:
        return self._step(self._redo, self._history, "沒有可以重做的動作")

    def _step(self, source: list, target: list, empty: str) -> bool:
        self._typing_run = False
        if not source:
            self._notice = empty
            return False
        target.append((list(self.keys), list(self.pins), self.cursor))
        self.keys, self.pins, self.cursor = source.pop()
        self.cand = None
        if not self.keys:
            history, redo = self._history, self._redo
            self._reset_buffer()  # (clears the history, which is still wanted)
            self._history, self._redo = history, redo
            return True
        self._redecode()
        return True

    def _forget_history(self) -> None:
        """Text was committed: older states no longer match the buffer."""
        self._history.clear()
        self._redo.clear()
        self._typing_run = False

    # ============================================================ editing
    def _insert(self, k: Key) -> None:
        self._checkpoint(typing=True)
        pos = self.cursor
        self.keys.insert(pos, k)
        kept = []
        for p in self.pins:
            if p.start >= pos:
                kept.append(_shift_segment(p, 1))
            elif p.end <= pos:
                kept.append(p)
            # a pin that spans the insertion point is dropped
        self.pins = kept
        self.cursor = pos + 1
        self._redecode()
        here = next((s for s in self.decoding.segments if s.start <= pos < s.end), None)
        # a finished syllable, a space or punctuation ends this undo step
        self._typing_run = not (k.char == " " or not k.char.isalnum() or (here is not None and here.kind is Kind.ZH))
        if self._retype_at is not None:
            self._retype_done()
            if self.correcting:
                return
        self._check_text_triggers()
        if self.cand is not None:
            return
        if self.cfg.commit_on_clause_punct and self.cursor == len(self.keys):
            last = self.decoding.segments[-1] if self.decoding.segments else None
            if last is not None and last.kind is Kind.PUNCT and last.text in CLAUSE_PUNCT:
                # The sentence is settled, so send it — but keep the mark
                # itself in the composition, so ↓ can still swap its width
                # (，<->, 。<->.). Committing the mark too made it the one
                # character that could never be corrected.
                self._commit_up_to(last.start)
                return
        self._commit_overflow()

    def _commit_up_to(self, pos: int) -> None:
        """Commit every segment that ends at or before key ``pos``."""
        while self.decoding.segments:
            first = self.decoding.segments[0]
            if first.end > pos:
                break
            self._commit += first.text
            self._text_here += first.text
            self._delete_keys(0, first.end)
            pos -= first.end
            self._forget_history()
            self._redecode()

    def _delete_keys(self, a: int, b: int) -> None:
        del self.keys[a:b]
        width = b - a
        kept = []
        for p in self.pins:
            if p.end <= a:
                kept.append(p)
            elif p.start >= b:
                kept.append(_shift_segment(p, -width))
        self.pins = kept
        if self.cursor >= b:
            self.cursor -= width
        elif self.cursor > a:
            self.cursor = a

    def _delete_unit(self, before: bool) -> None:
        """Backspace / Delete: remove exactly one character you can see —
        together with any hidden stray keys touching it (so they cannot
        reappear later) — and nothing else. Real typing logs showed the old
        behaviour surprising people: `…顯d` + Backspace became `…顯g` (a
        dropped key came back), `自己wj的` lost two letters at once."""
        units = self.decoding.units()
        if before:
            prev = [u for u in units if u[1] <= self.cursor]
            if not prev:
                a, b = 0, self.cursor  # only hidden keys before the cursor
            else:
                # the character before the cursor (an unfinished syllable's
                # keys are characters of their own: one key at a time), the
                # stray keys typed just before it, and any between it and
                # the cursor
                a, b = self._dropped_before(prev[-1][0]), self.cursor
        else:
            nxt = [u for u in units if u[0] >= self.cursor]
            a, b = self.cursor, (nxt[0][1] if nxt else len(self.keys))
        if a >= b:
            return
        self._checkpoint()
        self._delete_range(a, b)

    def _delete_range(self, a: int, b: int, stable: bool = True) -> None:
        """Delete keys [a, b) and decode again. With ``stable``, every other
        character stays exactly as it was on screen: the shorter buffer must
        not reveal a hidden stray key or merge neighbours into a different
        word. Where the decoder would change something, the old reading is
        pinned (only there)."""
        old = self.decoding
        self._delete_keys(a, b)
        if not self.keys:
            self._reset_buffer()
            return
        self._redecode()
        if not stable:
            return
        width = b - a
        expected = [(s, e, ch) for s, e, ch, _ in old.units() if e <= a] + \
                   [(s - width, e - width, ch) for s, e, ch, _ in old.units() if s >= b]
        hidden = {(s.start - (width if s.start >= b else 0)) for s in old.segments
                  if s.kind is Kind.DROP and (s.end <= a or s.start >= b)}

        def matches() -> bool:
            dec = self.decoding
            now_hidden = {s.start for s in dec.segments if s.kind is Kind.DROP}
            return [(s, e, ch) for s, e, ch, _ in dec.units()] == expected and hidden <= now_hidden

        if matches():
            return
        parts = [p for seg in old.segments for p in _parts_outside(seg, a, b) if p.kind is not Kind.PENDING]
        current = {(s.start, s.end, s.text, s.kind) for s in self.decoding.segments}
        for only_changed in (True, False):
            fixed = [p for p in parts if not (only_changed and (p.start, p.end, p.text, p.kind) in current)]
            self.pins = sorted([q for q in self.pins if all(q.end <= p.start or q.start >= p.end for p in fixed)]
                               + fixed, key=lambda p: p.start)
            self._redecode()
            if matches():
                return

    def _move_unit(self, delta: int) -> None:
        self._typing_run = False  # typing somewhere else is a new undo step
        self._retype_at = None
        units = self.decoding.units()
        if delta < 0:
            prev = [a for a, b, _, _ in units if b <= self.cursor]
            self.cursor = prev[-1] if prev else 0
        else:
            nxt = [b for a, b, _, _ in units if a >= self.cursor]
            self.cursor = nxt[0] if nxt else len(self.keys)
        self._refresh()

    def _commit_overflow(self) -> None:
        """Keep the composition from growing without bound.

        Never fires while a syllable is still being typed (that would decide
        the earlier text without the context of the syllable). When it fires,
        it commits down to well below the limit, so partial commits — each one
        ends and restarts the TSF composition — stay rare.
        """
        limit = self.cfg.max_buffer_chars
        segs = self.decoding.segments
        if len(self.decoding.units()) <= limit or not segs or segs[-1].kind is Kind.PENDING:
            return
        target = max(limit // 2, limit - 10)
        while len(self.decoding.units()) > target and len(self.decoding.segments) > 1:
            first = self.decoding.segments[0]
            if first.end > self.cursor:
                break
            self._commit += first.text
            self._text_here += first.text
            self._delete_keys(0, first.end)
            self._forget_history()
            self._redecode()

    def _reset_buffer(self) -> None:
        self._learned_here = []
        self._text_here = ""
        self.keys.clear()
        self.pins.clear()
        self.cursor = 0
        self.decoding = Decoding((), 0.0)
        self.suggestion = None
        # nothing left to correct
        self.correcting = False
        self.layer = "text"
        self._cycle = None
        self._retype_at = None
        self.smart = None  # committed: no longer editable
        self._forget_history()

    def _redecode(self) -> None:
        self.decoding = self.engine.decoder.decode(self.keys, self.pins, allow_english=self.mode is Mode.AUTO,
                                                   scheme=self.scheme)
        self._snap_cursor()
        self._update_suggestion()

    def _refresh(self) -> None:
        self._snap_cursor()
        self._update_suggestion()

    def _snap_cursor(self) -> None:
        self.cursor = max(0, min(self.cursor, len(self.keys)))
        for a, b, _, _ in self.decoding.units():
            if a < self.cursor < b:
                self.cursor = b
                break

    # ========================================================= candidates
    def _target_unit(self) -> int | None:
        units = self.decoding.units()
        if not units:
            return None
        if self.cursor >= len(self.keys):
            # At the end: the last real character (skip trailing spaces, so
            # "mvp␣" + ↓ offers alternatives for mvp).
            segs = self.decoding.segments
            idx = len(units) - 1
            while idx > 0 and segs[units[idx][3]].kind is Kind.SPACE:
                idx -= 1
            return idx
        for idx, (a, _, _, _) in enumerate(units):
            if a >= self.cursor:
                return idx
        return len(units) - 1

    def _new_list(self, items: list[Candidate], **kw) -> CandidateList:
        return CandidateList(items, self.cfg.candidates_per_page, multi=self.cfg.candidate_multi_column, **kw)

    def _open_candidates(self) -> None:
        items = self._candidate_items() + self._drop_candidates()
        if items:
            self.cand = self._new_list(items)
            # start on what is on screen now (your own words are listed
            # first, so the first item is not always the current text):
            # Enter keeps it, ↓ walks to the alternatives
            self.cand.index = self._current_index(items)
            self.cand._keep_visible()

    def _drop_candidates(self) -> list[Candidate]:
        """Keys just typed that the decoder threw away as slips, offered back.

        The hint says 「略過 e，↓ 可還原」 and until now ↓ did nothing about it:
        a dropped key produces no character, so it was not a candidate for
        anything (reported: 「有時候『略過』要取消現在都沒辦法」). Picking one
        keeps the key exactly as typed.
        """
        out = []
        window = len(self.keys) - 4
        for seg in self.decoding.segments:
            if seg.kind is not Kind.DROP or seg.end <= window:
                continue
            raw = "".join(k.char for k in self.keys[seg.start:seg.end])
            pin = Segment(seg.start, seg.end, raw, Kind.LITERAL, -10.0, pinned=True)
            out.append(Candidate(raw, pin, "保留這個鍵", group="略過的鍵"))
        return out

    def _candidate_items(self) -> list[Candidate]:
        t = self._target_unit()
        if t is None:
            return []
        units = self.decoding.units()
        a, b, _, seg_idx = units[t]
        seg = self.decoding.segments[seg_idx]
        # Candidates cross categories: Chinese <-> English <-> the raw keys,
        # so any wrong guess (o␣ vs ㄟ, i␣ vs 喔, mvp vs 勳) is one pick away.
        if seg.kind is Kind.ZH and self.scheme != "zhuyin":
            # pinyin: every tone of the syllables; Cangjie: every character
            # with the code (homophones by reading would be meaningless).
            # This character's own alternatives first (天 before 堤岸 for
            # "tian"), then longer words starting here.
            alts = self._zh_alternatives(a, own=True)
            alts.sort(key=lambda c: (c.pin.end != b, len(c.pin.readings) != 1))
            items = alts + self._raw_candidates(a, b)
        elif seg.kind is Kind.ZH:
            items = self._zh_candidates(units, t, at_end=self.cursor >= len(self.keys))
            items += self._raw_candidates(a, b)
        elif seg.kind is Kind.EN:
            items = _en_candidates(seg) + self._zh_alternatives(seg.start)
        elif seg.kind is Kind.PUNCT:
            items = self._punct_candidates(seg)
        elif seg.kind in (Kind.NUM, Kind.LITERAL):
            group = "數字" if seg.kind is Kind.NUM else "原始按鍵"
            items = [Candidate(seg.text, replace(seg, pinned=True), group=group)] + self._zh_alternatives(seg.start)
        else:
            items = []
        # Your own words first, then what you chose before, then the
        # dictionary (stable: the order within a group stays). The target's
        # own kind (英文, 數字, 標點) leads when it is not Chinese.
        lead = {Kind.EN: "英文", Kind.NUM: "數字", Kind.PUNCT: "標點"}.get(seg.kind)
        order = ([lead] if lead else []) + [g for g in GROUP_ORDER if g != lead]
        items.sort(key=lambda c: order.index(c.group) if c.group in order else len(order))
        seen: set[tuple[str, int, int]] = set()
        unique = []
        for c in items:
            key = (c.text, c.pin.start, c.pin.end)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique

    def _zh_alternatives(self, start: int, own: bool = False) -> list[Candidate]:
        """Chinese readings of the keys at ``start``. ``own``: they are the
        target's own candidates (group 詞庫), not another way to read
        something decoded as English/raw (group 其他讀法, noted with the
        reading so it is clear where it comes from)."""
        out = []
        for s in self.engine.decoder.zh_alternatives(self.keys, start, scheme=self.scheme):
            reading = "-".join(s.readings)
            note, group = self._note_group(s.text, reading)
            if not group:
                group = "詞庫" if own else "其他讀法"
                note = "" if own else reading.replace("-", " ")
            out.append(Candidate(s.text, replace(s, pinned=True), note, group=group))
        return out

    def _dropped_before(self, pos: int) -> int:
        """Start of the run of dropped (invisible) keys that ends at ``pos``."""
        dropped_ends = {s.end: s.start for s in self.decoding.segments if s.kind is Kind.DROP}
        while pos in dropped_ends:
            pos = dropped_ends[pos]
        return pos

    def _raw_candidates(self, a: int, b: int) -> list[Candidate]:
        """The keys exactly as typed (including stray keys dropped just
        before them), to undo any interpretation."""
        a = self._dropped_before(a)
        raw = "".join(k.char for k in self.keys[a:b])
        return [Candidate(raw, Segment(a, b, raw, Kind.LITERAL, -10.0, pinned=True), annotation="原始按鍵",
                          group="原始按鍵")]

    def _zh_candidates(self, units, t: int, at_end: bool) -> list[Candidate]:
        segs = self.decoding.segments
        # Maximal run of consecutive Chinese characters around the target.
        lo = t
        while lo > 0 and segs[units[lo - 1][3]].kind is Kind.ZH:
            lo -= 1
        hi = t
        while hi + 1 < len(units) and segs[units[hi + 1][3]].kind is Kind.ZH:
            hi += 1
        run = units[lo:hi + 1]
        readings = []
        for a, b, _, seg_idx in run:
            seg = segs[seg_idx]
            readings.append(seg.readings[seg.bounds.index(a)])
        ti = t - lo
        max_len = self.engine.lexicon.max_phrase_syllables
        spans = []
        if at_end:
            for length in range(min(max_len, ti + 1), 0, -1):
                spans.append((ti - length + 1, ti + 1))
        else:
            for length in range(min(max_len, len(run) - ti), 0, -1):
                spans.append((ti, ti + length))
        seen = set()
        items: list[Candidate] = []
        for s, e in spans:
            rs = tuple(readings[s:e])
            bounds = tuple(run[i][0] for i in range(s, e)) + (run[e - 1][1],)
            for text, score in self.engine.lexicon.phrases("-".join(rs)):
                key = (text, bounds[0], bounds[-1])
                if key in seen:
                    continue
                seen.add(key)
                pin = Segment(bounds[0], bounds[-1], text, Kind.ZH, score, rs, bounds, pinned=True)
                note, group = self._note_group(text, "-".join(rs))
                items.append(Candidate(text, pin, note, group=group or "詞庫"))
        return items

    def _note(self, phrase: str, reading: str) -> str:
        """Candidate annotation from my dictionary: its category, or 學過."""
        return self._note_group(phrase, reading)[0]

    def _note_group(self, phrase: str, reading: str) -> tuple[str, str]:
        """(annotation, group) from my dictionary: a word you added is in
        我的詞庫 (noted with its category), one you chose before in 學過."""
        e = self.engine.lexicon.entry(phrase, reading)
        if e is None:
            return "", ""
        if e.source == "manual" or e.category:
            return e.category or "我的詞庫", "我的詞庫"
        return ("學過", "學過") if e.count > 0 else ("", "")

    def _punct_candidates(self, seg: Segment) -> list[Candidate]:
        raw = self.keys[seg.start].char
        options = [seg.text]  # current choice first, then the other style
        if raw in FULLWIDTH_PUNCT:
            options += [FULLWIDTH_PUNCT[raw], raw, *PUNCT_VARIANTS.get(raw, "")]
        elif raw in PLAIN_PUNCT:  # pinyin / Cangjie: , . ; are punctuation keys
            options += [PLAIN_PUNCT[raw], raw]
        # Ctrl+, inserts 「，」 as the key itself, so there is no keycap to look
        # the variants up by: index them by the symbol as well.
        options += PUNCT_ALTERNATIVES.get(seg.text, "")
        return [Candidate(o, replace(seg, text=o, pinned=True), group="標點") for o in dict.fromkeys(options)]

    def _candidate_key(self, key: KeyInput) -> bool:
        cand = self.cand
        assert cand is not None
        vk = key.vk
        if key.ctrl and vk == VK_D:
            self._add_candidate_to_dict(cand.current)
            return True
        if key.ctrl or key.alt:
            return False
        if (key.char == ":" and cand.palette is not None
                and TABS[cand.palette % len(TABS)] != "搜尋符號"):
            # One more ':' from anywhere in the symbol-panel family jumps
            # straight into the searchable catalogue, ready to type a
            # keyword. ":：" alone still opens the ordinary panel instantly
            # (unchanged); a third ':' typed right after — or at any later
            # point while browsing — pivots into search instead of becoming
            # a literal colon. This is what makes a cold "：：：" land in the
            # search tab: the first two open the panel via the existing
            # trigger, and this is what the third one does once it's open.
            self._open_emoji()
            return True
        if cand.palette is not None:
            # Filtering by typing: gated on which tab is open, not on
            # snippet_at (which only the ;; trigger used to set — so Tab-
            # browsing to 片語 could not filter at all before this).
            tab = TABS[cand.palette % len(TABS)]
            if tab == "片語" and self._snippet_key(key):
                return True
            if tab == "搜尋符號" and self._emoji_key(key):
                return True
        elif cand.snippet_at is not None and self._snippet_key(key):
            # the ;; trigger's own 片語 list never sets cand.palette (it was
            # never a tab you Tab-cycle to in that path) — this is the
            # common case, not a fallback for an edge case
            return True
        if vk == VK_TAB and cand.palette is not None:
            self._open_palette(cand.palette + (-1 if key.shift else 1))
            return True
        if cand.palette is not None and TABS[cand.palette % len(TABS)] not in LIST_TABS and                 vk in (VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN):
            # The symbol panel is a grid, one page per row. Moving by ±1 used
            # to run off the end of a row into the next one, so → looked like
            # "down" and ↑↓ looked like nothing (reported: 「左右操作變成上下、
            # 上下操作變成左右」). Now each direction stays in its own axis.
            row, col = divmod(cand.index, cand.page_size)
            last_row = (len(cand.shown) - 1) // cand.page_size
            if vk in (VK_LEFT, VK_RIGHT):
                col = max(0, min(col + (1 if vk == VK_RIGHT else -1), cand.page_size - 1))
            else:
                row = max(0, min(row + (1 if vk == VK_DOWN else -1), last_row))
            cand.index = min(row * cand.page_size + col, len(cand.shown) - 1)
            cand._keep_visible()
            return True
        if vk == VK_TAB:
            # show one group at a time: 全部 -> 我的詞庫 -> 學過 -> 詞庫 -> …
            cand.cycle_filter(-1 if key.shift else +1)
            return True
        digit = key.digit  # top row, or the keypad with NumLock either way
        if digit and digit in SELECTION_DIGITS:
            i = SELECTION_DIGITS.index(digit)
            page = cand.page_items()  # the column the selection is in
            if i < len(page):
                self._choose(page[i])
            return True
        if vk == VK_DELETE:
            self._forget_candidate(cand.current)
        elif vk in (VK_RETURN, VK_SPACE):
            self._choose(cand.current)
        elif vk == VK_DOWN:
            cand.move(+1)
        elif vk == VK_UP:
            cand.move(-1)
        elif vk in (VK_LEFT, VK_RIGHT):
            # ← → walk the row of group chips at the top of the window — the
            # thing they point at. 微軟注音 keeps paging on PageUp/PageDown,
            # and ↑↓ already roll over into the next page, so a dedicated
            # paging arrow was spending the two most reachable keys on the
            # rarest action. Shift+→ still opens another column.
            step = +1 if vk == VK_RIGHT else -1
            if cand.multi:
                cand.move_column(step, self.cfg.candidate_expand)
            else:
                cand.move_page(step)
        elif vk == VK_NEXT:
            cand.move_page(+1)
        elif vk == VK_PRIOR:
            cand.move_page(-1)
        elif vk in (VK_ESCAPE, VK_BACK):
            self.cand = None
        else:
            return False
        return True

    def _choose(self, c: Candidate) -> None:
        if c.pin is None and not c.symbol and c.suggestion is None:
            return  # a placeholder row (「還沒有片語」)
        if c.symbol and (len(c.symbol) > 1 or c.snippet_id is not None):
            self._type_text(c)
            return
        if c.symbol:
            self._insert_symbol(c.symbol)
            return
        if c.suggestion is not None:
            self.cand = None
            self._accept_suggestion(c.suggestion)
            return
        pin = c.pin
        replaced = self._text_over(pin.start, pin.end)
        self._checkpoint()
        self.pins = [p for p in self.pins if p.end <= pin.start or p.start >= pin.end]
        self.pins.append(pin)
        self.pins.sort(key=lambda p: p.start)
        self.cand = None
        if self.correcting:
            self._redecode()
            self._learn_choice(pin, replaced)
            self.cursor = pin.start
            self._snap_to_unit()
            return
        if self.cursor < len(self.keys):
            self.cursor = pin.end
        self._redecode()
        self._learn_choice(pin, replaced)

    def _text_over(self, a: int, b: int) -> str:
        """The characters on screen for the keys [a, b)."""
        return "".join(ch for s, _, ch, _ in self.decoding.units() if a <= s < b)

    def _current_index(self, items: list[Candidate]) -> int:
        """Position of the text on screen now among ``items`` (else 0)."""
        for i, c in enumerate(items):
            if c.pin is not None and c.text == self._text_over(c.pin.start, c.pin.end):
                return i
        return 0

    # ============================================================ memory
    def _learn(self, seg: Segment, origin: str = "pick") -> bool:
        """Remember an explicit choice (candidate picked, Tab accepted).
        True if the phrase was new to my memory."""
        user = self.engine.user
        if user is None or not self.cfg.learn:
            return False
        if seg.kind is Kind.ZH:
            new = user.learn(seg.text, "-".join(seg.readings), "zh", origin)
        elif seg.kind is Kind.EN:
            new = user.learn(seg.text.lower(), "", "en", origin)
        else:
            return False
        self.engine.lexicon.invalidate()
        if new and origin == "fix":
            # provisional: a later fix in the same sentence may replace the
            # character this pair was built around (see _prune_learned)
            self._learned_here.append((seg.text if seg.kind is Kind.ZH else seg.text.lower(),
                                       "-".join(seg.readings) if seg.kind is Kind.ZH else ""))
        if new and self.cfg.learn_notice:
            # once per word: learning is visible, and so is how to undo it
            how = "（修正）" if origin == "fix" else ""
            self._notice = f"記住了「{seg.text}」{how}· 選字框裡按 Delete 可忘記"
        return new

    def _learn_choice(self, pin: Segment, replaced: str) -> None:
        """A candidate was chosen for ``pin``'s keys, where ``replaced`` was
        on screen. Picking a word, or keeping what was there, is remembered
        as it is. Changing one character inside Chinese text is a
        *correction*: the character alone says little (boosting it
        everywhere would cause new mistakes), so it is remembered together
        with its neighbour as a word — the context it belongs to — and the
        same sentence comes out right next time (user feedback #2)."""
        if pin.kind is not Kind.ZH or len(pin.readings) != 1 or replaced in ("", pin.text):
            self._learn(pin)
            return
        contexts = self._correction_contexts(pin)
        if not contexts:
            self._learn(pin)
            return
        for ctx in contexts:
            self._learn(ctx, origin="fix")

    def _correction_contexts(self, pin: Segment) -> list[Segment]:
        """Two-character words made of the corrected character and its
        left or right Chinese neighbour (as now on screen). If one of them is
        a real word, just that one; otherwise both (one of them is the word
        the user means — the settings page shows them to sort or delete)."""
        units = self.decoding.units()
        segs = self.decoding.segments
        idx = next((i for i, u in enumerate(units) if u[0] == pin.start), None)
        if idx is None:
            return []

        def zh_unit(i):
            if 0 <= i < len(units) and segs[units[i][3]].kind is Kind.ZH:
                a, b, ch, si = units[i]
                return a, b, ch, segs[si].readings[segs[si].bounds.index(a)]
            return None

        here = zh_unit(idx)
        out = []
        for left, right in ((zh_unit(idx - 1), here), (here, zh_unit(idx + 1))):
            if left is None or right is None:
                continue
            readings = (left[3], right[3])
            text = left[2] + right[2]
            out.append(Segment(left[0], right[1], text, Kind.ZH, 0.0, readings, (left[0], left[1], right[1]),
                               pinned=True))
        real = [s for s in out if self.engine.lexicon.in_system(s.text, "-".join(s.readings))]
        return real[:1] if real else out

    def _forget_candidate(self, c: Candidate) -> None:
        user = self.engine.user
        seg = c.pin
        if seg is None:
            # Not a decoded word: a symbol, a kaomoji, a snippet, or a 超智慧
            # 推薦 continuation (those carry a Suggestion instead of a pin).
            # Delete is wired unconditionally in _candidate_key, so every one
            # of these used to crash the backend here (seg.kind on None) —
            # found while building the searchable symbol panel. Say why
            # instead, and leave the window open.
            if c.group == "我的符號" and user is not None and c.symbol:
                # the one group here that *is* the user's own content: let
                # Delete remove it on the spot, the same as forgetting a
                # learned word, instead of forcing a trip to Settings
                if user.remove_custom_symbol(c.symbol):
                    self._notice = f"已刪除「{c.symbol}」"
                    keep_index = self.cand.index if self.cand else 0
                    self.cand = None
                    self._open_palette(TABS.index("我的符號"))
                    if self.cand is not None:
                        self.cand.index = min(keep_index, len(self.cand.shown) - 1)
                else:
                    self._notice = "已經刪除過了"
            elif c.group == "片語":
                self._notice = "片語要到設定頁「片語與顏文字」管理"
            elif c.suggestion is not None:
                self._notice = "接續建議沒辦法忘記；不想看到就繼續打別的字"
            else:
                self._notice = "這不是可以忘記的詞"
            return
        if user is None or seg.kind not in (Kind.ZH, Kind.EN):
            return
        reading = "-".join(seg.readings) if seg.kind is Kind.ZH else ""
        phrase = seg.text if seg.kind is Kind.ZH else seg.text.lower()
        result = user.forget(phrase, reading, "zh" if seg.kind is Kind.ZH else "en")
        self.engine.lexicon.invalidate()
        self._notice = {
            "manual": f"「{seg.text}」是你加入的詞，要刪除請到設定頁",
            "forgot": f"已忘記「{seg.text}」的使用紀錄",
            "blocked": f"不再建議「{seg.text}」（可在設定頁還原）",
        }[result]
        # Rebuild the window without the removed/demoted entry.
        keep_index = self.cand.index if self.cand else 0
        self.cand = None
        self._redecode()
        self._open_candidates()
        if self.cand is not None:
            self.cand.index = min(keep_index, len(self.cand.shown) - 1)

    def _add_candidate_to_dict(self, c: Candidate) -> None:
        seg = c.pin
        if seg.kind is Kind.ZH:
            self._add_to_dict(seg.text, "-".join(seg.readings), "zh")
        elif seg.kind in (Kind.EN, Kind.LITERAL) and seg.text.strip():
            self._add_to_dict(seg.text.strip(), "", "en")

    def _add_composition_to_dict(self) -> None:
        """Ctrl+D while composing: add the Chinese text before the cursor
        (e.g. a friend's name just typed and fixed) to my dictionary."""
        units = [u for u in self.decoding.units() if u[1] <= self.cursor]
        segs = self.decoding.segments
        chars, readings = [], []
        for a, b, ch, seg_idx in reversed(units):
            seg = segs[seg_idx]
            if seg.kind is not Kind.ZH:
                break
            chars.append(ch)
            readings.append(seg.readings[seg.bounds.index(a)])
        if not chars:
            self._notice = "游標前沒有中文可以加入詞庫"
            return
        chars.reverse()
        readings.reverse()
        self._add_to_dict("".join(chars), "-".join(readings), "zh")

    def _add_to_dict(self, phrase: str, reading: str, kind: str) -> None:
        user = self.engine.user
        if user is None:
            return
        category = self.cfg.default_category if kind == "zh" else "常用英文"
        user.add(phrase, reading, kind, category)
        self.engine.lexicon.invalidate()
        self._notice = f"已加入詞庫：{phrase}（{category}）"

    # ========================================================= assistance
    def _hint_parts(self) -> tuple[str, str, str, str]:
        """(reading, becomes, dropped, info) — the hint box's content, apart,
        so the panel can lay it out and ``_hint`` can still make one string
        for PIME's own message window."""
        if not self.decoding.segments:
            return "", "", "", ""
        layout = self.engine.layout
        last = self.decoding.segments[-1]
        if self.cursor == len(self.keys):
            pending = last.kind is Kind.PENDING and self.cfg.spelling_hint
            if pending and self.scheme == "cangjie":
                # 字根 of the code so far, and the character it would give
                radicals = "".join(CANGJIE_RADICALS.get(c, c) for c in last.text)
                chars = self.engine.lexicon.cangjie_chars(last.text)
                return radicals, (chars[0] if chars else ""), "", ""
            reading = ""
            if pending and self.scheme == "zhuyin":
                # Show what the keys will become, in canonical order (k2 -> ㄉㄜ).
                canon = bopomofo.canonical(layout.symbol(c) or "" for c in last.text)
                reading = canon or layout.symbols_for_keys(last.text)
            # A key just typed was treated as a stray and is not shown
            # (pup -> up): say so, so a wrong guess is not silent.
            return reading, "", self._recent_drops(), ""
        # Cursor moved back to fix something: annotate the character after
        # the cursor with its reading and the keys behind it, so stray
        # letters and wrong guesses are easy to spot.
        if not self.cfg.key_hint_on_move:
            return "", "", "", ""
        return "", "", "", self._unit_info()

    def _hint(self) -> str:
        reading, becomes, dropped, info = self._hint_parts()
        if info:
            return info
        if becomes:
            return reading + f" → {becomes}（空白鍵）"
        if dropped:
            return f"（略過 {dropped}，↓ 可還原）" + reading
        return reading

    def _recent_drops(self, window: int = 4) -> str:
        """Keys among the last ``window`` typed that the decoder dropped."""
        n = len(self.keys)
        return "".join(self.keys[s.start].char for s in self.decoding.segments
                       if s.kind is Kind.DROP and s.start >= n - window)

    def _unit_context(self, t: int, width: int = 3) -> str:
        """The sentence around unit ``t`` with ［ ］ on it, so it is clear
        which character is being changed: 今天［針］對數."""
        units = self.decoding.units()
        show = lambda u: "␣" if u[2] == " " else u[2]  # noqa: E731
        before = "".join(show(u) for u in units[max(0, t - width):t])
        after = "".join(show(u) for u in units[t + 1:t + 1 + width])
        lead = "…" if t > width else ""
        tail = "…" if t + 1 + width < len(units) else ""
        return f"{lead}{before}［{show(units[t])}］{after}{tail}"

    def _unit_info(self) -> str:
        """「…前文［字］後文　注音 ⌨ 按鍵」for the character after the cursor,
        with any stray keys dropped just before it."""
        t = self._target_unit()
        if t is None:
            return ""
        layout = self.engine.layout
        a, b, ch, seg_idx = self.decoding.units()[t]
        seg = self.decoding.segments[seg_idx]
        start = self._dropped_before(a)
        dropped = "".join(k.char for k in self.keys[start:a])
        raw = "".join(k.char for k in self.keys[a:b])
        context = self._unit_context(t)
        if seg.kind is Kind.ZH:
            text = f"{context}　{seg.readings[seg.bounds.index(a)]}  ⌨ {raw}"
        else:
            sym = (layout.symbol(raw) or layout.tone(raw)) if self.scheme == "zhuyin" else None
            text = f"{context}　⌨ {raw}" + (f"（ㄅ: {sym}）" if sym else "")
        if dropped:
            text = f"（略過 {dropped}）" + text
        return text

    def _trailing_run(self, limit: int = 3) -> list[tuple[int, int, str, str]]:
        """(key_start, key_end, char, reading) of the Chinese characters at
        the end of the composition (at most ``limit``)."""
        segs = self.decoding.segments
        run = []
        for a, b, ch, seg_idx in reversed(self.decoding.units()):
            seg = segs[seg_idx]
            if seg.kind is not Kind.ZH:
                break
            run.append((a, b, ch, seg.readings[seg.bounds.index(a)]))
            if len(run) == limit:
                break
        run.reverse()
        return run

    def _update_smart(self) -> None:
        """超智慧推薦: recompute when the Chinese text at the end changed;
        while something else is being typed, keep the last one (stale)."""
        if not self.cfg.smart_suggest or self.correcting or self.cand is not None:
            return
        segs = self.decoding.segments
        if self.cursor != len(self.keys) or not segs or segs[-1].kind is not Kind.ZH:
            if self.smart is not None:
                self.smart.stale = True
            return
        from . import predict

        run = self._trailing_run(4)
        tail = [(u[2], u[3]) for u in run]
        # only continue from a word boundary (see predict.chains)
        seg_starts = {x.start for x in segs}
        starts = frozenset(k for k in range(1, len(tail[-3:]) + 1) if run[-k][0] in seg_starts)
        chains = []
        for c in predict.chains(self.engine.lexicon, tail[-3:], self.cfg.autocomplete_min_score, starts=starts):
            sug = self._make_suggestion(run[-1:], c.text, c.readings, c.score)
            if sug is not None:
                chains.append(sug)
        fixes = []
        for k, word in predict.alternatives(self.engine.lexicon, tail):
            part = run[-k:]
            readings = tuple(u[3] for u in part)
            bounds = tuple(u[0] for u in part) + (part[-1][1],)
            pin = Segment(part[0][0], part[-1][1], word, Kind.ZH, 0.0, readings, bounds, pinned=True)
            fixes.append(Candidate(word, pin, "".join(u[2] for u in part), group="也許是"))
        # the context shown in front of every chain starts at a word
        # boundary, or it reads as a slice of nothing (「們今天會不會有」)
        whole = [k for k in range(len(tail), 0, -1) if run[-k][0] in seg_starts]
        n = next((k for k in whole if k <= 3), min(3, len(tail)))
        self.smart = Smart(chains, fixes, context="".join(c for c, _ in tail[-n:]))

    def _make_suggestion(self, tail, text: str, readings: tuple[str, ...], score: float) -> "Suggestion | None":
        """A continuation of ``text`` after the trailing characters ``tail``
        (whose readings are kept), as the keys to append and the pin."""
        dec = self.engine.decoder
        typed = [dec.unit_keys(self.scheme, ch, syl) for ch, syl in zip(text, readings)]
        if not typed or not all(typed):
            return None
        keys = [Key(c) for t in typed for c in t]
        bounds = [u[0] for u in tail] + [tail[-1][1]]
        pos = tail[-1][1]
        for t in typed:
            pos += len(t)
            bounds.append(pos)
        phrase = "".join(u[2] for u in tail) + text
        pin = Segment(tail[0][0], pos, phrase, Kind.ZH, score, tuple(u[3] for u in tail) + tuple(readings),
                      tuple(bounds), pinned=True)
        return Suggestion(text, pin, keys)

    def _update_suggestion(self) -> None:
        self._update_smart()
        self.suggestion = None
        self.suggestions = []
        if (not self.cfg.autocomplete or self.cand is not None or self.cursor != len(self.keys)
                or self.correcting):
            return
        segs = self.decoding.segments
        if not segs or segs[-1].kind is not Kind.ZH:
            return
        run = self._trailing_run()
        lex = self.engine.lexicon
        dec = self.engine.decoder
        scheme = self.scheme
        found: list[Suggestion] = []
        seen: set[str] = set()
        for k in range(len(run), 0, -1):
            tail = run[-k:]
            prefix = "".join(u[2] for u in tail)
            prefix_reading = "-".join(u[3] for u in tail)
            # A single character is weak context; only suggest common phrases.
            min_score = self.cfg.autocomplete_min_score + (SINGLE_CHAR_SUGGEST_MARGIN if k == 1 else 0.0)
            for phrase, reading, score in lex.completions(prefix, limit=24):
                if score < min_score:
                    break
                if not reading.startswith(prefix_reading + "-") or len(phrase) - k > 3:
                    continue
                if phrase[k:] in seen:
                    continue
                extra = reading.split("-")[k:]
                typed = [dec.unit_keys(scheme, ch, syl) for ch, syl in zip(phrase[k:], extra)]
                if not all(typed):
                    continue  # a character this scheme can't type
                keys = [Key(c) for t in typed for c in t]
                bounds = [u[0] for u in tail] + [tail[-1][1]]
                pos = tail[-1][1]
                for t in typed:
                    pos += len(t)
                    bounds.append(pos)
                pin = Segment(tail[0][0], pos, phrase, Kind.ZH, score,
                              tuple(reading.split("-")), tuple(bounds), pinned=True)
                found.append(Suggestion(phrase[k:], pin, keys))
                seen.add(phrase[k:])
                if len(found) >= MAX_SUGGESTIONS:
                    break
            if len(found) >= MAX_SUGGESTIONS:
                break
        self.suggestions = found
        self.suggestion = found[0] if found else None

    def _smart_items(self) -> list[Candidate]:
        """Pickable 超智慧推薦 items, in the order the panel numbers them."""
        smart = self.smart
        if smart is None or smart.stale:
            return []
        return [Candidate(s.text, None, "接下來", suggestion=s, group="長句") for s in smart.chains] + \
            [replace(f) for f in smart.fixes]

    def _open_continuations(self) -> None:
        """Shift+Tab: all continuations in the candidate window (with
        超智慧推薦 on: its chains and homophones first, numbered as in its panel)."""
        items = self._smart_items()
        items += [Candidate(s.text, None, s.pin.text, suggestion=s, group="接續") for s in self.suggestions]
        if not items:
            self._notice = "現在沒有接續建議"
            return
        self.cand = self._new_list(items, title="接續")

    # ============================================================ symbol panel
    def _newline_modifier(self, key: KeyInput) -> bool:
        """Does this Enter mean "send it and break the line"?

        Off by default. Shift+Enter was tried as the default and taken back:
        in most editors Shift+Enter already means something, and having the
        input method hand it over changed what those editors did. The chooser
        is in the settings page, and the symbol panel's ⏎ always works
        whatever is set here.
        """
        want = self.cfg.newline_enter
        if want == "off":
            return False
        if want == "shift":
            return key.shift and not key.ctrl and not key.alt
        if want == "ctrl":
            return key.ctrl and not key.shift and not key.alt
        if want == "right-shift":
            return key.shift and not key.ctrl and not key.alt and key.scan in (SCAN_RSHIFT, 0)
        return False

    def _is_palette_key(self, key: KeyInput) -> bool:
        return self.cfg.palette_hotkey == "rctrl" and key.vk == VK_CONTROL and key.extended

    def _is_palette_tap(self, key: KeyInput) -> bool:
        """A lone tap of the symbol-panel key: right Ctrl (default) or
        right Alt. (Keys pressed *with* Alt never reach an input method in
        Windows/PIME, so Ctrl+Alt+, cannot work.) Right Ctrl held longer is
        voice input; right Alt makes some apps open their menu bar, which is
        why right Ctrl is the default (user feedback #8)."""
        if self._palette_down_at is None or not self._is_palette_key(key):
            return False
        return time.monotonic() - self._palette_down_at <= CTRL_TAP_SECONDS

    def toggle_palette(self) -> None:
        if self.cand is not None and self.cand.palette is not None:
            self.cand = None
        else:
            self._open_palette(0)

    def _open_palette(self, index: int) -> None:
        index %= len(TABS)
        name = TABS[index]
        tabs = " ".join(f"[{n}]" if i == index else n for i, n in enumerate(TABS))
        # Carried across Tab-cycling: without this, Tab-ing from the panel
        # "::" opened into any other category and picking something left the
        # literal "::" sitting in the composition forever (_insert_symbol's
        # cleanup only fires when trigger_at is not None, and _open_palette
        # used to silently drop it on every call). Found while wiring up
        # 搜尋符號 — reproduced with 'ji3::{TAB}1' leaving '我::「' behind.
        trigger_at = self.cand.trigger_at if self.cand is not None else None
        if name == "片語":
            items = self._snippet_items("")
        elif name == "顏文字":
            items = self._kaomoji_items()
        elif name == "我的符號":
            items = self._my_symbol_items()
        elif name == "搜尋符號":
            items = self._emoji_items("")
        else:
            _, symbols = self.engine.symbols.category(index)
            items = [Candidate(sym, None, symbol=sym, group="符號") for sym in symbols]
            # the category name rides on the first row, so it is visible even
            # when nothing is being composed (no message window then)
            items[0].annotation = f"{name} · Tab 換分類"
        self.cand = self._new_list(items, title=f"符號 {tabs} · Tab 換分類", palette=index)
        self.cand.multi = True
        # open a few columns straight away: the point of the panel is seeing
        # a lot at once. 片語 lines are long, so it stays at one.
        self.cand.columns = 1 if name == "片語" else min(self.cand.pages, 2 if name in LIST_TABS else 6)
        self.cand.trigger_at = trigger_at

    def _open_emoji(self) -> None:
        self._open_palette(TABS.index("搜尋符號"))

    # ============================================================ 片語 / 顏文字
    def _snippet_items(self, query: str) -> list[Candidate]:
        user = self.engine.user
        rows = user.snippets(query) if user is not None else []
        items = []
        for r in rows:
            first = r["body"].strip().splitlines()[0] if r["body"].strip() else ""
            label = r["title"] or (first[:18] + ("…" if len(first) > 18 or "\n" in r["body"].strip() else ""))
            items.append(Candidate(label, None, r["keyword"], symbol=r["body"], group="片語", preview=r["body"],
                                   snippet_id=r["id"]))
        if not items:
            note = "沒有符合的片語" if query else "還沒有片語：到設定頁「片語」新增"
            items = [Candidate(f"（{note}）", None, group="片語")]
        return items

    def _kaomoji_items(self) -> list[Candidate]:
        return [Candidate(face, None, symbol=face, group=group) for face, group in self.engine.symbols.kaomoji()]

    def _check_text_triggers(self) -> None:
        """Typing a trigger opens a panel without a hotkey: ``;;`` the 片語
        list (letters after it filter), ``::`` the symbol panel (Tab reaches
        希臘字母, 數學, 片語, 顏文字 …).

        Both are here because the hotkey alone was not enough: right Alt
        never reaches an input method in some apps, and a key nobody told you
        about is a key nobody uses.
        """
        if self.correcting or self.cand is not None or self.cursor != len(self.keys):
            return
        def typed(n: int) -> str:
            """The last ``n`` keys — but not when they sit inside an English
            or numeric token, so C++'s ``std::vector`` keeps its scope
            operator instead of opening the symbol panel."""
            if len(self.keys) < n:
                return ""
            before = len(self.keys) - n - 1
            if before >= 0:
                seg = next((x for x in self.decoding.segments if x.start <= before < x.end), None)
                if seg is not None and seg.kind in (Kind.EN, Kind.NUM):
                    return ""
            return "".join(k.char for k in self.keys[-n:])

        trig = self.cfg.snippet_trigger
        if trig and typed(len(trig)) == trig:
            self.cand = self._new_list(self._snippet_items(""), title="片語")
            self.cand.snippet_at = self.cand.trigger_at = len(self.keys) - len(trig)
            return
        trig = self.cfg.palette_trigger
        if trig and typed(len(trig)) == trig:
            self._open_palette(0)
            if self.cand is not None:
                self.cand.trigger_at = len(self.keys) - len(trig)

    def _snippet_key(self, key: KeyInput) -> bool:
        """Keys while the 片語 list is open: letters filter it, digits pick,
        Backspace edits the filter, Esc closes it keeping what was typed."""
        cand = self.cand
        vk = key.vk
        if vk == VK_BACK:
            if cand.query:
                self.keys.pop()
                self.cursor = len(self.keys)
                self._redecode()
                self._refilter_snippets(cand.query[:-1])
            else:
                self.cand = None
                if cand.trigger_at is not None:
                    self._delete_unit(before=True)  # back to the first ";"
                # Tab-reached with no ";;" ever typed: nothing to delete —
                # without this guard it deleted whatever character happened
                # to sit before the cursor, unrelated to the panel at all.
            return True
        if vk == VK_ESCAPE:
            self.cand = None  # what was typed stays (;; can still be typed)
            return True
        if key.printable and not key.ctrl and not key.alt and key.char not in SELECTION_DIGITS and key.char != " ":
            if cand.trigger_at is None:
                # Tab-reached, no preceding ";;": the first filter letter is
                # where cleanup-on-pick must start, or picking something
                # would commit the typed-to-filter letters as if they were
                # ordinary text in front of it.
                cand.trigger_at = len(self.keys)
            self.keys.append(Key(key.char))
            self.cursor = len(self.keys)
            self._redecode()
            self._refilter_snippets(cand.query + key.char)
            return True
        return False

    def _refilter_snippets(self, query: str) -> None:
        at = self.cand.snippet_at
        trigger = self.cand.trigger_at
        palette = self.cand.palette  # dropped here before: 2nd letter of a
        # Tab-reached (not ;;-typed) filter had nothing left to route it to
        # _snippet_key, since that path has no snippet_at either — it fell
        # through to ordinary typing after exactly one letter
        self.cand = self._new_list(self._snippet_items(query), title="片語", palette=palette)
        self.cand.snippet_at, self.cand.trigger_at, self.cand.query = at, trigger, query

    # ============================================================ 搜尋符號 / 我的符號
    def _emoji_items(self, query: str) -> list[Candidate]:
        """The built-in searchable catalogue (symbols.EMOJI_SYMBOLS), matched
        against its category label and search tags — plus the much bigger
        downloadable catalogue (symbols_extra.py) when it has been fetched
        *and* turned on in Settings. Off by default and never fetched by
        itself, the same shape as voice_enabled: nothing changes here for
        anyone who hasn't opted in.

        Grouped the same way 顏文字 already is (see SymbolPanel.kaomoji):
        recently used ones pulled into their own "最近" group up front, the
        rest kept in their natural category group (星星, 愛心, …) — no text
        next to each symbol. The symbol is the whole point of looking at it;
        a label next to every single one was clutter 顏文字 never had either.
        """
        from .symbols import EMOJI_SYMBOLS, RECENT_KAOMOJI

        q = query.strip().lower()
        pool = EMOJI_SYMBOLS
        if self.cfg.symbols_extra_enabled:
            from . import symbols_extra

            extra = symbols_extra.load()
            if extra:
                pool = pool + extra
        if q:
            pool = [e for e in pool if q in e[1].lower() or any(q in tag for tag in e[2])]
        if not pool:
            note = f"沒有符合「{query}」的符號" if query else "沒有符號"
            return [Candidate(f"（{note}）", None, group="搜尋符號")]
        in_pool = {sym for sym, _cat, _tags in pool}
        recent = [s for s in self.engine.symbols.recent if s in in_pool][:RECENT_KAOMOJI]
        items = [Candidate(sym, None, symbol=sym, group="最近") for sym in recent]
        # a few symbols are deliberately in more than one category (♥ is
        # both 愛心 and 花色) — keep every occurrence, the same way flat()
        # would for 顏文字, just skip the copies already shown under 最近
        items += [Candidate(sym, None, symbol=sym, group=cat) for sym, cat, _tags in pool if sym not in recent]
        return items

    def _my_symbol_items(self) -> list[Candidate]:
        """The user's own pasted symbols/kaomoji (settings page「片語與顏文字」），
        most recently used first — the same shared recent-symbols tracking
        every other category already uses, not a separate count of its own."""
        user = self.engine.user
        rows = user.custom_symbols() if user is not None else []
        if not rows:
            return [Candidate("（還沒有：到設定頁「片語與顏文字」貼上）", None, group="我的符號")]
        recent = {sym: i for i, sym in enumerate(self.engine.symbols.recent)}
        rows = sorted(rows, key=lambda t: recent.get(t, len(rows) + 1))
        return [Candidate(text, None, symbol=text, group="我的符號") for text in rows]

    def _emoji_key(self, key: KeyInput) -> bool:
        """Keys while 搜尋符號 is open: letters filter it, digits pick,
        Backspace edits the filter. Esc is not handled here on purpose — the
        generic Esc/Backspace-with-nothing-typed fallback at the end of
        _candidate_key already does exactly the right thing (close it)."""
        cand = self.cand
        vk = key.vk
        if vk == VK_BACK:
            if cand.query:
                self.keys.pop()
                self.cursor = len(self.keys)
                self._redecode()
                self._refilter_emoji(cand.query[:-1])
            else:
                self.cand = None
                if cand.trigger_at is not None:
                    self._delete_unit(before=True)
            return True
        if key.printable and not key.ctrl and not key.alt and key.char not in SELECTION_DIGITS and key.char != " ":
            if cand.trigger_at is None:
                cand.trigger_at = len(self.keys)
            self.keys.append(Key(key.char))
            self.cursor = len(self.keys)
            self._redecode()
            self._refilter_emoji(cand.query + key.char)
            return True
        return False

    def _refilter_emoji(self, query: str) -> None:
        trigger = self.cand.trigger_at
        title = f"搜尋符號 · 關鍵字：{query}" if query else "搜尋符號 · 打關鍵字篩選"
        self.cand = self._new_list(self._emoji_items(query), title=title, palette=TABS.index("搜尋符號"))
        self.cand.multi = True
        self.cand.columns = min(self.cand.pages, 2)
        self.cand.trigger_at, self.cand.query = trigger, query

    def _type_text(self, c: Candidate) -> None:
        """Type a 片語 / 顏文字 as it is. The ;; that opened the list (and
        its filter) is removed; the text before it is committed first."""
        at = self.cand.trigger_at if self.cand is not None else None
        self.cand = None
        if at is not None:
            del self.keys[at:]
            self.cursor = len(self.keys)
            self.pins = [p for p in self.pins if p.end <= at]
            self._redecode() if self.keys else self._reset_buffer()
        self.commit_all()
        self._commit += c.symbol
        if c.snippet_id is not None and self.engine.user is not None:
            self.engine.user.used_snippet(c.snippet_id)
        else:
            self.engine.symbols.used(c.symbol)

    def _insert_symbol(self, symbol: str) -> None:
        if symbol == NEWLINE_SYMBOL:
            # Remote desktops sometimes swallow the Shift of Shift+Enter, and
            # not every application has another line-break key. Picking this
            # sends the text and a newline after it.
            at = self.cand.trigger_at if self.cand is not None else None
            self.cand = None
            if at is not None:
                del self.keys[at:]
                self.cursor = len(self.keys)
                self.pins = [p for p in self.pins if p.end <= at]
                self._redecode() if self.keys else self._reset_buffer()
            self.engine.symbols.used(symbol)
            self.commit_all()
            self._commit += "\n"
            return
        return self._insert_symbol_at_cursor(symbol)

    def _insert_symbol_at_cursor(self, symbol: str) -> None:
        at = self.cand.trigger_at if self.cand is not None else None
        self.cand = None
        self.engine.symbols.used(symbol)
        if at is not None:  # the :: that opened the panel is not text
            del self.keys[at:]
            self.cursor = len(self.keys)
            self.pins = [p for p in self.pins if p.end <= at]
            self._redecode() if self.keys else self._reset_buffer()
        if not self.keys:
            self._commit += symbol  # nothing being composed: type it right away
            return
        pos = self.cursor
        self._insert(Key(symbol))
        # keep it exactly as chosen (the decoder never reinterprets it)
        pin = Segment(pos, pos + 1, symbol, Kind.PUNCT, -1.0, pinned=True)
        self.pins = [p for p in self.pins if p.end <= pos or p.start >= pos + 1] + [pin]
        self.pins.sort(key=lambda p: p.start)
        self._redecode()

    def _accept_suggestion(self, sug: Suggestion) -> None:
        self._checkpoint()
        start = len(self.keys)
        self.keys.extend(sug.keys)
        pin = sug.pin
        self.pins = [p for p in self.pins if p.end <= pin.start]
        self.pins.append(pin)
        self.cursor = len(self.keys)
        assert pin.end == start + len(sug.keys)
        self._learn(pin, origin="tab")  # positive feedback: accepted continuations rank higher
        self._redecode()
        self._commit_overflow()


def _shift_segment(seg: Segment, delta: int) -> Segment:
    return replace(
        seg,
        start=seg.start + delta,
        end=seg.end + delta,
        bounds=tuple(b + delta for b in seg.bounds),
    )


def _parts_outside(seg: Segment, a: int, b: int) -> list[Segment]:
    """The pieces of ``seg`` outside the deleted keys [a, b), positioned for
    the buffer after the deletion, as pins. A Chinese phrase splits only at
    syllable edges; everything else has one character per key."""
    width = b - a
    if seg.end <= a:
        return [replace(seg, pinned=True)]
    if seg.start >= b:
        return [replace(_shift_segment(seg, -width), pinned=True)]
    out = []
    if seg.kind is Kind.ZH:
        if seg.start < a and a in seg.bounds:
            k = seg.bounds.index(a)
            out.append(replace(seg, end=a, text=seg.text[:k], readings=seg.readings[:k],
                               bounds=seg.bounds[:k + 1], pinned=True))
        if seg.end > b and b in seg.bounds:
            k = seg.bounds.index(b)
            out.append(replace(seg, start=a, end=seg.end - width, text=seg.text[k:], readings=seg.readings[k:],
                               bounds=tuple(x - width for x in seg.bounds[k:]), pinned=True))
    elif seg.kind is not Kind.DROP:
        if seg.start < a:
            out.append(replace(seg, end=a, text=seg.text[:a - seg.start], pinned=True))
        if seg.end > b:
            out.append(replace(seg, start=a, end=seg.end - width, text=seg.text[b - seg.start:], pinned=True))
    return out


def _en_candidates(seg: Segment) -> list[Candidate]:
    word = seg.text
    variants = dict.fromkeys([word, word.lower(), word.upper(), word[:1].upper() + word[1:].lower()])
    return [Candidate(v, replace(seg, text=v, pinned=True), group="英文") for v in variants]
