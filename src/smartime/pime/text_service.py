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

ID_MODE_ICON = 1  # left click on the tray icon: same as a Shift tap
ID_ABOUT = 3
# Right-click menu entries for the three modes.
MODE_MENU_IDS = {10: Mode.AUTO, 11: Mode.CHINESE, 12: Mode.ENGLISH}
MODE_ICONS = {Mode.AUTO: "auto.ico", Mode.CHINESE: "chinese.ico", Mode.ENGLISH: "english.ico"}

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
        self._composing = False  # a composition existed after our previous reply

    # ------------------------------------------------------------------
    def handle(self, msg: dict) -> dict:
        method = msg.get("method")
        reply: dict = {}
        ret = None
        success = True
        s = self.session

        if method in ("filterKeyDown", "onActivate"):
            # Pick up edits from the settings app (config, my dictionary).
            try:
                self.engine.refresh()
            except Exception:
                log.exception("refresh failed")

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
            command = msg.get("id")
            if command == ID_MODE_ICON:
                s.toggle_mode()
            elif command in MODE_MENU_IDS:
                s.set_mode(MODE_MENU_IDS[command])
            self._render(reply)
        elif method == "onMenu":
            ret = [{"text": mode.label, "id": cid, "checked": s.mode is mode}
                   for cid, mode in MODE_MENU_IDS.items()]
            ret += [{}, {"text": "關於智慧輸入法", "id": ID_ABOUT}]
        elif method == "onCompartmentChanged":
            pass
        elif method == "onKeyboardStatusChanged":
            self.keyboard_open = bool(msg.get("opened", True))
            if not self.keyboard_open:
                s.reset()
                self._clear_ui(reply)
            self._update_mode_icon(reply, force=True)
        elif method == "onCompositionTerminated":
            if msg.get("forced", False):
                # The app ended our composition (click elsewhere, focus
                # change); TSF already left the text in the document.
                s.reset()
                self._clear_ui(reply, composition=False)
            else:
                # PIME ended it itself: that is the echo of our own commit
                # (commitString ends the old composition, then PIME starts a
                # new one for the remaining text). Keep the buffer — resetting
                # here broke long sentences after an automatic partial commit.
                log.debug("composition ended by our own commit; keeping buffer")
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
            notes = v.candidate_notes or [""] * len(v.candidates)
            # Category / 學過 / 原始按鍵 shown after the candidate text.
            reply["candidateList"] = [f"{t}　{n}" if n else t for t, n in zip(v.candidates, notes)]
            reply["candidateCursor"] = v.candidate_index
            reply["showCandidates"] = True
            self._showing_candidates = True
        elif self._showing_candidates:
            reply["candidateList"] = []
            reply["showCandidates"] = False
            self._showing_candidates = False

        if v.notice:
            message = v.notice
        elif v.hint:
            message = v.hint
        elif v.suggestion:
            message = f"{v.suggestion}  ⇥Tab"
        else:
            message = ""
        if not v.composition:
            message = ""
        # PIME applies showMessage *before* the composition update, and when
        # no composition exists yet it opens a temporary one and ends it at
        # the end of the reply — which commits our first key as raw text.
        # So never show a message in the reply that starts the composition;
        # it appears from the next key on.
        if not self._composing:
            message = ""
        self._composing = bool(v.composition)
        if message != self._message:
            if message:
                reply["showMessage"] = {"message": message, "duration": MESSAGE_DURATION}
            else:
                reply["hideMessage"] = True
            self._message = message

        self._update_mode_icon(reply)

    def _clear_ui(self, reply: dict, composition: bool = True) -> None:
        self._composing = False
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
        button = {
            "id": "windows-mode-icon",
            "icon": str(self.icon_dir / MODE_ICONS[mode]),
            "tooltip": f"智慧輸入法：{mode.label}（Shift 切換英文，右鍵選模式）",
            "commandId": ID_MODE_ICON,
            "enable": self.keyboard_open,
        }
        reply.setdefault("addButton" if add else "changeButton", []).append(button)
