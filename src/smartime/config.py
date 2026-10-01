"""User-tunable settings, persisted as JSON in the user data folder.

Every field has a safe default so a missing or partial config file is fine;
unknown keys and values of the wrong type are ignored (forward compatibility
with newer versions, and the settings app cannot write garbage).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

TOGGLE_SHIFT_CHOICES = ("left", "right", "both", "none")
MODE_CHOICES = ("auto", "chinese", "english")
DROP_CHOICES = ("off", "conservative", "standard")
# Values written by older versions.
_MODE_ALIASES = {"mixed": "auto"}


@dataclass
class Config:
    # Keyboard and modes
    layout: str = "dachen"
    toggle_shift: str = "right"  # which lone Shift tap toggles English <-> the Chinese-side mode
    shift_cycle: str = "two"  # "two": 英文 <-> 中文側模式；"three": 自動 -> 純中文 -> 純英文 循環
    start_mode: str = "auto"  # "auto"（中英自動）| "chinese"（純中文）| "english"（純英文）

    # Candidate window
    candidates_per_page: int = 9
    candidate_font: str = "Microsoft JhengHei UI"
    candidate_font_size: int = 16
    vertical_candidates: bool = True

    # Composition behaviour
    max_buffer_chars: int = 30  # older text is committed automatically beyond this
    commit_on_clause_punct: bool = True  # ，。？！：； commit the buffer

    # Ctrl+symbol -> full-width punctuation (微軟新注音 / 華碩 convention),
    # in the Chinese-side modes only so Ctrl+, / Ctrl+. still reach apps in English mode.
    ctrl_punctuation: bool = True
    # Symbol keys normally give full-width punctuation (Shift+1 -> ！,
    # Shift+; -> ：). Symbols listed here stay half-width instead. Default: the
    # double quote, which the user expects to be " (not ；, which is Ctrl+;).
    # The other form is always one ↓ away in the candidate window.
    halfwidth_symbols: str = '"'

    # Smart correction
    reorder_tolerance: bool = True  # ㄛㄨˇ typed for ㄨㄛˇ still gives 我
    drop_stray_keys: str = "standard"  # "off" | "conservative" | "standard"
    single_letter_context: bool = True  # lone i / o are zhuyin unless English context

    # Memory (my dictionary)
    learn: bool = True  # remember candidates I pick and continuations I accept
    default_category: str = "常用詞"  # where Ctrl+D puts a new word

    # Assistance
    spelling_hint: bool = True  # show zhuyin of the unfinished syllable
    key_hint_on_move: bool = True  # cursor moved back: show 字 注音 ⌨ 按鍵
    autocomplete: bool = True  # Tab to accept a phrase continuation
    suggestion_count: int = 3  # continuations shown next to the composition
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
            self.shift_cycle = "two"
        self.start_mode = _MODE_ALIASES.get(self.start_mode, self.start_mode)
        if self.start_mode not in MODE_CHOICES:
            self.start_mode = "auto"
        if self.drop_stray_keys not in DROP_CHOICES:
            self.drop_stray_keys = "standard"
        self.candidates_per_page = max(1, min(9, self.candidates_per_page))
        self.candidate_font_size = max(10, min(32, self.candidate_font_size))
        self.max_buffer_chars = max(10, min(80, self.max_buffer_chars))
        self.suggestion_count = max(1, min(5, self.suggestion_count))
        if not self.default_category.strip():
            self.default_category = "常用詞"

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
