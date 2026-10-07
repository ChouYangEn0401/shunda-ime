"""User-tunable settings, persisted as JSON in the user data folder.

Every field has a safe default so a missing or partial config file is fine;
unknown keys and values of the wrong type are ignored (forward compatibility
with newer versions, and the settings app cannot write garbage).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

TOGGLE_SHIFT_CHOICES = ("left", "right", "both", "none")
MODE_CHOICES = ("auto", "chinese", "english", "pinyin", "cangjie")
SCHEME_CHOICES = ("zhuyin", "pinyin", "cangjie")
DROP_CHOICES = ("off", "conservative", "standard")
# Values written by older versions.
_MODE_ALIASES = {"mixed": "auto"}


@dataclass
class Config:
    # Keyboard and modes
    layout: str = "dachen"  # "dachen"（大千）| "eten"（倚天）
    toggle_shift: str = "right"  # which lone Shift tap toggles English <-> the Chinese-side mode
    shift_cycle: str = "three"  # "three": mode_cycle 裡的模式輪流；"two": 英文 <-> 上次用的中文模式
    start_mode: str = "auto"  # "auto"（中英自動）| "chinese"（純注音）| "english" | "pinyin" | "cangjie"
    # How 中英自動 types Chinese: one scheme at a time, mixed with English
    # (the same letters mean different things in each scheme).
    chinese_scheme: str = "zhuyin"  # "zhuyin"（注音）| "pinyin"（拼音）| "cangjie"（倉頡五代）
    # Modes a Shift tap cycles through, in this order (comma separated).
    mode_cycle: str = "auto,chinese,english"

    # Candidate window
    candidates_per_page: int = 9
    candidate_font: str = "Microsoft JhengHei UI"
    candidate_font_size: int = 16
    vertical_candidates: bool = True
    # → opens the next page as another column (← on the first column folds
    # back) instead of turning the page; the IME's own panel only.
    candidate_multi_column: bool = False

    # Composition behaviour
    max_buffer_chars: int = 30  # older text is committed automatically beyond this
    commit_on_clause_punct: bool = True  # ，。？！：； commit the buffer

    # Ctrl+symbol -> full-width punctuation (微軟新注音 / 華碩 convention),
    # in the Chinese-side modes only so Ctrl+, / Ctrl+. still reach apps in English mode.
    ctrl_punctuation: bool = True
    # What symbol keys type alone / with Shift (see engine/punct.py):
    # "keycap" = what is printed on the key (Shift+, -> <), Chinese
    # punctuation comes from Ctrl (default; no two combinations type the same);
    # "fullwidth" = Shift+, -> ，like Ctrl+, (older, Microsoft-like);
    # "custom" = per symbol, from halfwidth_symbols.
    punct_style: str = "keycap"
    # "custom" style: symbols listed here type half-width, the others
    # full-width. The other form is always one ↓ away in the candidate window.
    halfwidth_symbols: str = '"'
    # Ctrl / Ctrl+Shift cells changed by the user: "C+," / "CS+/" -> text
    # ("" = leave that combination to the app).
    punct_overrides: dict = field(default_factory=dict)
    # Symbol panel: "rctrl" = a lone tap of the right Ctrl key (default; holding
    # it is voice input), "ralt" = a lone tap of the right Alt key (some apps
    # also open their menu bar on it), or "off". ` is left alone (users fence
    # code with it). Ctrl+Alt+key is impossible: Windows does not pass keys
    # pressed with Alt to input methods.
    palette_hotkey: str = "rctrl"
    # 片語: typing this opens the list of saved texts (then a keyword filters
    # it). Never valid zhuyin, very rare in English; "" turns it off.
    snippet_trigger: str = ";;"
    # Text trigger for the symbol panel, the same idea as ;; for 片語 ("" = off).
    # The hotkey alone was not discoverable, and right Alt never reaches an
    # input method in some applications.
    palette_trigger: str = "::"

    # Smart correction
    reorder_tolerance: bool = True  # ㄛㄨˇ typed for ㄨㄛˇ still gives 我
    drop_stray_keys: str = "standard"  # "off" | "conservative" | "standard"
    single_letter_context: bool = True  # lone i / o are zhuyin unless English context

    # Chromium-based apps (Edge, Chrome, VS Code, Teams, ...) sometimes end the
    # composition by themselves while still showing it; keep the text so the
    # next key puts it back instead of losing it. User-caused endings (click,
    # Ctrl+Enter, window switch) always clear.
    keep_on_app_interrupt: bool = True

    # Correction mode: Esc while composing enters it (Vim-like); off = Esc clears
    correction_mode: bool = True

    # On-screen panels drawn by the IME itself (smartime.ui), docked under
    # the hint box. Decode panel (按鍵／注音／國字 in columns): "correction"
    # = in correction mode only (default), "always" = whenever composing, "off".
    panel_decode: str = "correction"
    panel_theme: str = "system"  # "system" | "light" | "dark"
    # The candidate window drawn as a panel: groups in colour (我的詞庫, 學過,
    # 詞庫 …), Tab filters a group. Off = PIME's plain list.
    panel_candidates: bool = True
    # Draw the hint strip ourselves instead of PIME's message window (a pale
    # yellow Windows 95 tooltip that PIME rebuilds on every change, so it
    # blinked on every keystroke). Off falls back to PIME's own box.
    panel_hint: bool = True
    # Keep the strip on screen for as long as there is a composition, even
    # with nothing to say, as a dot. Some editors (Sublime Text) draw no
    # underline under composing text, so a click elsewhere could drop a whole
    # sentence with no warning.
    composing_indicator: bool = True

    # Memory (my dictionary)
    learn: bool = True  # remember candidates I pick and continuations I accept
    learn_notice: bool = True  # say so the first time a word is learned
    default_category: str = "人工加入"  # where Ctrl+D puts a new word

    # Voice input (hold right Ctrl, speak, release)
    # Ask GitHub once a day whether there is a newer release. One plain
    # HTTPS GET to a public API, no account and no identifier beyond a
    # User-Agent naming the product; nothing is ever installed without the
    # user starting it. Turn it off and the input method never goes online.
    update_check: bool = True

    voice_enabled: bool = False  # off until a model is downloaded and the user turns it on
    voice_engine: str = "auto"  # "auto" | "breeze" (GPU) | "sensevoice" (CPU)
    voice_hotwords: bool = True  # my dictionary's own words help recognition
    voice_traditional: bool = True  # convert to Taiwan Traditional Chinese

    # Assistance
    spelling_hint: bool = True  # show zhuyin of the unfinished syllable
    key_hint_on_move: bool = True  # cursor moved back: show 字 注音 ⌨ 按鍵
    autocomplete: bool = True  # Tab to accept a phrase continuation
    suggestion_count: int = 3  # continuations shown next to the composition
    # Experimental (off by default): 超智慧推薦 — a second panel with longer
    # chains of what may come next and homophones of the word just typed.
    smart_suggest: bool = False
    # Experimental (off by default): 瘋狂模式 — type only the start of each
    # character's zhuyin (initial, or the first symbols; no tone) and keep
    # going: ㄨㄇ -> 我們. The decode panel then shows keys / zhuyin / text all the time.
    crazy_mode: bool = False
    autocomplete_min_score: float = -5.5

    @classmethod
    def from_dict(cls, data: dict, base: Config | None = None) -> Config:
        """Apply known keys with the right types onto ``base`` (or defaults)."""
        cfg = cls(**asdict(base)) if base is not None else cls()
        known = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key not in known:
                continue
            default = getattr(cfg, key)
            if isinstance(default, dict):
                if isinstance(value, dict):
                    setattr(cfg, key, {str(k): str(v) for k, v in value.items() if isinstance(v, str)})
                continue
            if isinstance(default, bool) != isinstance(value, bool):
                continue
            if isinstance(default, (int, float)) and not isinstance(value, (int, float)):
                continue
            if isinstance(default, str) and not isinstance(value, str):
                continue
            setattr(cfg, key, type(default)(value))
        cfg._normalize()
        return cfg

    def _normalize(self) -> None:
        if self.toggle_shift not in TOGGLE_SHIFT_CHOICES:
            self.toggle_shift = "right"
        if self.shift_cycle not in ("two", "three"):
            self.shift_cycle = "three"
        self.start_mode = _MODE_ALIASES.get(self.start_mode, self.start_mode)
        if self.start_mode not in MODE_CHOICES:
            self.start_mode = "auto"
        if self.chinese_scheme not in SCHEME_CHOICES:
            self.chinese_scheme = "zhuyin"
        wanted = {m.strip() for m in self.mode_cycle.split(",")}
        cycle = [m for m in MODE_CHOICES if m in wanted]
        self.mode_cycle = ",".join(cycle or ["auto", "chinese", "english"])
        if self.palette_hotkey not in ("rctrl", "ralt", "off"):
            self.palette_hotkey = "rctrl"
        if self.layout not in ("dachen", "eten"):
            self.layout = "dachen"
        if self.voice_engine not in ("auto", "breeze", "sensevoice"):
            self.voice_engine = "auto"
        if self.drop_stray_keys not in DROP_CHOICES:
            self.drop_stray_keys = "standard"
        if len(self.snippet_trigger) > 4 or self.snippet_trigger.strip() != self.snippet_trigger:
            self.snippet_trigger = ";;"
        if len(self.palette_trigger) > 4 or self.palette_trigger.strip() != self.palette_trigger:
            self.palette_trigger = "::"
        if self.palette_trigger and self.palette_trigger == self.snippet_trigger:
            self.palette_trigger = ""  # one trigger cannot open two panels
        if self.punct_style not in ("keycap", "fullwidth", "custom"):
            self.punct_style = "keycap"
        self.punct_overrides = {k: v[:4] for k, v in self.punct_overrides.items()
                                if re.fullmatch(r"CS?\+.", k) and len(v) <= 4}
        if self.panel_decode not in ("off", "correction", "always"):
            self.panel_decode = "correction"
        if self.panel_theme not in ("system", "light", "dark"):
            self.panel_theme = "system"
        self.candidates_per_page = max(1, min(9, self.candidates_per_page))
        self.candidate_font_size = max(10, min(32, self.candidate_font_size))
        self.max_buffer_chars = max(10, min(80, self.max_buffer_chars))
        self.suggestion_count = max(1, min(9, self.suggestion_count))
        if not self.default_category.strip():
            self.default_category = "人工加入"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: Path) -> Config:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as e:
            log.warning("config: cannot read %s (%s); using defaults", path, e)
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
