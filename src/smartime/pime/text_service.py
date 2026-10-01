"""Adapter between PIME text-service requests and an engine Session.

One instance per PIME client (i.e. per input context in an application).
The reply dict uses PIME's field names (compositionString, commitString,
candidateList, showMessage, ...), see PIME's python/textService.py.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..engine.keys import (
    VK_CAPITAL, VK_CONTROL, VK_LMENU, VK_MENU, VK_RMENU, VK_SHIFT, KeyInput,
)
from ..engine.session import Engine, Mode, Session

log = logging.getLogger(__name__)

ID_MODE_ICON = 1
ID_TOGGLE_MODE = 2
ID_ABOUT = 3

MESSAGE_DURATION = 3600  # seconds; we hide the message explicitly
SELECTION_KEYS = "123456789"


def key_from_msg(msg: dict) -> KeyInput:
    states = msg.get("keyStates") or [0] * 256

    def down(vk: int) -> bool:
        return (states[vk] & 0x80) != 0

    char_code = msg.get("charCode", 0)
    return KeyInput(
        vk=msg.get("keyCode", 0),
        char=chr(char_code) if char_code else "",
        shift=down(VK_SHIFT),
        ctrl=down(VK_CONTROL),
        alt=down(VK_MENU) or down(VK_LMENU) or down(VK_RMENU),
        caps=(states[VK_CAPITAL] & 0x01) != 0,
        scan=msg.get("scanCode", 0),
    )


class SmartTextService:
    def __init__(self, engine: Engine, icon_dir: Path):
        self.engine = engine
        self.icon_dir = icon_dir
        self.session = Session(engine)
        self.keyboard_open = True
        self.is_windows8_above = True
        self._message = ""
        self._showing_candidates = False
        self._mode_shown: Mode | None = None

    # ------------------------------------------------------------------
    def handle(self, msg: dict) -> dict:
        method = msg.get("method")
        reply: dict = {}
        ret = None
        success = True
        s = self.session

        if method == "init":
            self.is_windows8_above = bool(msg.get("isWindows8Above", True))
        elif method == "onActivate":
            self.keyboard_open = bool(msg.get("isKeyboardOpen", True))
            self._on_activate(reply)
        elif method == "onDeactivate":
            s.reset()
            self._clear_ui(reply)
            reply.setdefault("removeButton", []).append("windows-mode-icon")
            self._mode_shown = None
        elif method == "filterKeyDown":
            ret = self.keyboard_open and s.filter_key_down(key_from_msg(msg))
        elif method == "onKeyDown":
            ret = self.keyboard_open and s.key_down(key_from_msg(msg))
            self._render(reply)
        elif method == "filterKeyUp":
            ret = self.keyboard_open and s.filter_key_up(key_from_msg(msg))
        elif method == "onKeyUp":
            ret = self.keyboard_open and s.key_up(key_from_msg(msg))
            self._render(reply)
        elif method == "onPreservedKey":
            ret = False
        elif method == "onCommand":
            if msg.get("id") in (ID_MODE_ICON, ID_TOGGLE_MODE):
                s.toggle_mode()
            self._render(reply)
        elif method == "onMenu":
            ret = [
                {"text": "切換 中英混合 / 純英文", "id": ID_TOGGLE_MODE},
                {"text": "關於智慧輸入法", "id": ID_ABOUT},
            ]
        elif method == "onCompartmentChanged":
            pass
        elif method == "onKeyboardStatusChanged":
            self.keyboard_open = bool(msg.get("opened", True))
            if not self.keyboard_open:
                s.reset()
                self._clear_ui(reply)
            self._update_mode_icon(reply, force=True)
        elif method == "onCompositionTerminated":
            # The app ended our composition (click elsewhere, focus change).
            # Whatever was on screen has been committed by TSF already.
            s.reset()
            self._clear_ui(reply, composition=False)
        else:
            success = False

        if ret is not None:
            reply["return"] = bool(ret) if method.startswith(("filter", "onKey")) else ret
        reply["success"] = success
        reply["seqNum"] = msg.get("seqNum", 0)
        return reply

    # ------------------------------------------------------------------
    def _on_activate(self, reply: dict) -> None:
        cfg = self.engine.config
        reply["customizeUI"] = {
            "candFontName": cfg.candidate_font,
            "candFontSize": cfg.candidate_font_size,
            "candPerRow": 1 if cfg.vertical_candidates else cfg.candidates_per_page,
            "candUseCursor": True,
        }
        reply["setSelKeys"] = SELECTION_KEYS[: cfg.candidates_per_page]
        self._update_mode_icon(reply, force=True, add=True)

    def _render(self, reply: dict) -> None:
        v = self.session.view()
        if v.commit:
            reply["commitString"] = v.commit
        reply["compositionString"] = v.composition
        if v.composition:
            reply["compositionCursor"] = v.cursor

        if v.candidates is not None:
            reply["candidateList"] = v.candidates
            reply["candidateCursor"] = v.candidate_index
            reply["showCandidates"] = True
            self._showing_candidates = True
        elif self._showing_candidates:
            reply["candidateList"] = []
            reply["showCandidates"] = False
            self._showing_candidates = False

        if v.hint:
            message = v.hint
        elif v.suggestion:
            message = f"{v.suggestion}  ⇥Tab"
        else:
            message = ""
        if not v.composition:
            message = ""
        if message != self._message:
            if message:
                reply["showMessage"] = {"message": message, "duration": MESSAGE_DURATION}
            else:
                reply["hideMessage"] = True
            self._message = message

        self._update_mode_icon(reply)

    def _clear_ui(self, reply: dict, composition: bool = True) -> None:
        if composition:
            reply["compositionString"] = ""
        if self._showing_candidates:
            reply["candidateList"] = []
            reply["showCandidates"] = False
            self._showing_candidates = False
        if self._message:
            reply["hideMessage"] = True
            self._message = ""

    def _update_mode_icon(self, reply: dict, force: bool = False, add: bool = False) -> None:
        mode = self.session.mode
        if not force and mode is self._mode_shown:
            return
        self._mode_shown = mode
        if not self.is_windows8_above:
            return
        name = "mixed.ico" if mode is Mode.MIXED else "english.ico"
        button = {
            "id": "windows-mode-icon",
            "icon": str(self.icon_dir / name),
            "tooltip": "智慧輸入法：中英混合" if mode is Mode.MIXED else "智慧輸入法：純英文",
            "commandId": ID_MODE_ICON,
            "enable": self.keyboard_open,
        }
        reply.setdefault("addButton" if add else "changeButton", []).append(button)
