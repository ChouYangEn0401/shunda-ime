"""User-tunable settings, persisted as JSON in the user data folder.

Every field has a safe default so a missing or partial config file is fine;
unknown keys are ignored (forward compatibility with newer versions).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

TOGGLE_SHIFT_CHOICES = ("left", "right", "both", "none")
MODE_CHOICES = ("auto", "chinese", "english")
# Values written by older versions.
_MODE_ALIASES = {"mixed": "auto"}


@dataclass
class Config:
    # Keyboard
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
    # in mixed mode only so Ctrl+, / Ctrl+. still reach apps in English mode.
    ctrl_punctuation: bool = True
    # Symbol keys normally give full-width punctuation (Shift+1 -> ！,
    # Shift+; -> ：). Symbols listed here stay half-width instead. Default: the
    # double quote, which the user expects to be " (not ；, which is Ctrl+;).
    # The other form is always one ↓ away in the candidate window.
    halfwidth_symbols: str = '"'

    # Assistance
    spelling_hint: bool = True  # show zhuyin of the unfinished syllable
    autocomplete: bool = True  # Tab to accept a phrase continuation
    autocomplete_min_score: float = -5.5

    @classmethod
    def load(cls, path: Path) -> Config:
        cfg = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cfg
        except (OSError, ValueError) as e:
            log.warning("config: cannot read %s (%s); using defaults", path, e)
            return cfg
        known = {f.name: f for f in fields(cls)}
        for key, value in data.items():
            f = known.get(key)
            if f is None:
                continue
            default = getattr(cfg, key)
            if isinstance(default, bool) != isinstance(value, bool):
                continue
            if isinstance(default, (int, float)) and not isinstance(value, (int, float)):
                continue
            if isinstance(default, str) and not isinstance(value, str):
                continue
            setattr(cfg, key, type(default)(value))
        if cfg.toggle_shift not in TOGGLE_SHIFT_CHOICES:
            cfg.toggle_shift = "right"
        if cfg.shift_cycle not in ("two", "three"):
            cfg.shift_cycle = "two"
        cfg.start_mode = _MODE_ALIASES.get(cfg.start_mode, cfg.start_mode)
        if cfg.start_mode not in MODE_CHOICES:
            cfg.start_mode = "auto"
        cfg.candidates_per_page = max(1, min(9, cfg.candidates_per_page))
        return cfg

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
