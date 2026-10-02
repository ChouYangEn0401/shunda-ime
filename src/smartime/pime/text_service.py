"""Adapter between PIME text-service requests and an engine Session.

One instance per PIME client (i.e. per input context in an application).
The reply dict uses PIME's field names (compositionString, commitString,
candidateList, showMessage, ...), see PIME's python/textService.py.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from ..engine.keys import (
    MODIFIER_VKS, SCAN_LSHIFT, SCAN_RSHIFT, VK_CAPITAL, VK_CONTROL, VK_LMENU, VK_LSHIFT, VK_MENU, VK_RMENU,
    VK_RSHIFT, VK_SHIFT, KeyInput,
)
from .. import PRODUCT_NAME
from ..engine.session import Engine, Mode, Session
from .winapp import KEEP_APPS, foreground_app, mouse_clicked

log = logging.getLogger(__name__)

ID_MODE_ICON = 1  # left click on the tray icon: same as a Shift tap
ID_ABOUT = 3
ID_SETTINGS = 4
# Right-click menu entries for the three modes.
MODE_MENU_IDS = {10: Mode.AUTO, 11: Mode.CHINESE, 12: Mode.ENGLISH, 13: Mode.PINYIN, 14: Mode.CANGJIE}
MODE_ICONS = {Mode.AUTO: "auto.ico", Mode.CHINESE: "chinese.ico", Mode.ENGLISH: "english.ico",
              Mode.PINYIN: "pinyin.ico", Mode.CANGJIE: "cangjie.ico"}

MESSAGE_DURATION = 3600  # seconds; we hide the message explicitly
SELECTION_KEYS = "123456789"


def _panel_window(create: bool):
    """The panel window (smartime.ui.overlay), or None where it cannot exist."""
    try:
        from ..ui import overlay
    except Exception:  # noqa: BLE001 - not on Windows, or a broken install: plain PIME windows
        return None
    return overlay.get() if create else overlay._overlay


def key_from_msg(msg: dict) -> KeyInput:
    states = msg.get("keyStates") or [0] * 256

    def down(vk: int) -> bool:
        return (states[vk] & 0x80) != 0

    char_code = msg.get("charCode", 0)
    vk = msg.get("keyCode", 0)
    scan = msg.get("scanCode", 0)
    if vk == VK_SHIFT and not scan:
        # PIME always sends scanCode 0, so tell the left and right Shift
        # apart by which one the key state says is down (needed for the
        # "toggle with the right/left Shift" setting).
        scan = SCAN_RSHIFT if down(VK_RSHIFT) else SCAN_LSHIFT if down(VK_LSHIFT) else 0
    return KeyInput(
        vk=vk,
        char=chr(char_code) if char_code else "",
        shift=down(VK_SHIFT),
        ctrl=down(VK_CONTROL),
        alt=down(VK_MENU) or down(VK_LMENU) or down(VK_RMENU),
        caps=(states[VK_CAPITAL] & 0x01) != 0,
        scan=scan,
        extended=bool(msg.get("isExtended", False)),
    )


class SmartTextService:
    # PIME keeps one icon cache per *application process* and destroys every
    # icon in it whenever any of that process's input contexts deactivates
    # (LangBarButton::clearIconCache). The mode buttons of the app's other
    # windows keep the dead handle: the 自/中/英 icon vanishes from the
    # taskbar, or shows whatever icon or cursor later reuses the handle.
    # PIME reloads an icon only when its file path changes, so after any
    # deactivation every other button is re-sent under the other spelling of
    # its path (icons\auto.ico <-> icons\.\auto.ico, the same file).
    _icons_cleared = 0  # deactivations/closes seen by this backend

    @classmethod
    def icons_invalidated(cls) -> None:
        cls._icons_cleared += 1

    def __init__(self, engine: Engine, icon_dir: Path):
        self.engine = engine
        self.icon_dir = icon_dir
        self.session = Session(engine)
        self.keyboard_open = True
        self.is_windows8_above = True
        self._message = ""
        self._showing_candidates = False
        self._mode_shown: Mode | None = None
        self._icon_epoch = SmartTextService._icons_cleared
        self._icon_variant = 0  # which spelling of the icon path was sent last
        self._composing = False  # a composition existed after our previous reply
        self._clicked_while_composing = False
        self._passthrough_at = 0.0
        self._composing_app = ""

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
            SmartTextService.icons_invalidated()
        elif method == "filterKeyDown":
            key = key_from_msg(msg)
            # (reading also forgets clicks before this key, e.g. the one that focused the field)
            if mouse_clicked() and s.composing and self._composing:
                self._clicked_while_composing = True
            ret = self.keyboard_open and s.filter_key_down(key)
            if not ret and key.vk not in MODIFIER_VKS:
                # a key that goes to the app (Ctrl+Enter, Ctrl+A, ...): if the
                # composition ends right after, the user caused it
                self._passthrough_at = time.monotonic()
        elif method == "onKeyDown":
            if self._clicked_while_composing:
                # The mouse was clicked while text was still composing (the
                # caret may be somewhere else now, and some apps keep the
                # composition open): commit it where it is, then this key
                # starts afresh at the caret.
                self._clicked_while_composing = False
                if s.composing and self._composing:
                    log.info("mouse clicked while composing: committing %d chars", len(s.decoding.text))
                    s.commit_all()
                    self._composing = False  # this reply starts a new composition
            ret = self.keyboard_open and s.key_down(key_from_msg(msg))
            if not ret:
                self._passthrough_at = time.monotonic()  # committed, then sent on to the app
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
            elif command in (ID_SETTINGS, ID_ABOUT):
                self._open_settings("about" if command == ID_ABOUT else "")
            self._render(reply)
        elif method == "onMenu":
            # every mode this lexicon supports, Shift cycle or not
            ret = [{"text": s.mode_label() if mode is Mode.AUTO else mode.label, "id": cid, "checked": s.mode is mode}
                   for cid, mode in MODE_MENU_IDS.items() if s._available(mode)]
            ret += [{}, {"text": "設定…", "id": ID_SETTINGS}, {"text": f"關於{PRODUCT_NAME}", "id": ID_ABOUT}]
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
                # The app ended our composition. Usually the user did it
                # (click, window switch, Ctrl+Enter) and the text stays in
                # the document. But Chromium-based editors that re-render
                # (blur/focus) end it *spontaneously* while the page keeps
                # the old composition, and our next composition replaces it:
                # the text vanished ("後面的內容遺失"). In that case keep the
                # buffer, so the next update re-sends the whole text.
                app = foreground_app()
                keep = s.composing and self._spontaneous_end(app)
                if s.composing:
                    log.info("composition ended by the app: app=%s chars=%d keys=%d correcting=%s kept=%s",
                             app or "?", len(s.decoding.text), len(s.keys), s.correcting, keep)
                if keep:
                    self._composing = False  # PIME starts a new composition
                    self._clear_ui(reply, composition=False)
                else:
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

        if self._icon_epoch != SmartTextService._icons_cleared:
            # another input context deactivated: our icon handle may be dead
            self._icon_epoch = SmartTextService._icons_cleared
            if self._mode_shown is not None and "addButton" not in reply:
                self._icon_variant ^= 1
                self._update_mode_icon(reply, force=True)

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
        if cfg.voice_enabled:
            try:
                from ..voice import launch

                launch.start()  # no-op when already running
            except Exception:
                log.exception("cannot start the voice service")

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
        elif v.candidates is not None and v.candidate_title:
            message = v.candidate_title
        elif v.hint:
            message = v.hint
        elif v.suggestion:
            others = v.suggestions[1:]
            message = f"{v.suggestion}  ⇥Tab" + "".join(f" · {s}" for s in others)
            if others:
                message += "　Shift+Tab 全部"
        else:
            message = ""
        if not v.composition:
            message = ""
        if self._show_panel(v) and v.correcting and not v.notice and v.candidates is None:
            # the panel shows everything; the hint box stays as its anchor
            message = "修正模式 · i 回到打字"
        # PIME applies showMessage *before* the composition update, and when
        # no composition exists yet it opens a temporary one and ends it at
        # the end of the reply — which commits our first key as raw text.
        # So never show a message in the reply that starts the composition;
        # it appears from the next key on.
        if not self._composing:
            message = ""
            if v.composition:
                self._composing_app = foreground_app()  # where this composition lives
        self._composing = bool(v.composition)
        if message != self._message:
            if message:
                reply["showMessage"] = {"message": message, "duration": MESSAGE_DURATION}
            else:
                reply["hideMessage"] = True
            self._message = message

        self._update_mode_icon(reply)

    def _show_panel(self, v) -> bool:
        """Show / hide our own panel window for this view. True if shown."""
        overlay = _panel_window(create=v.panel is not None)
        if overlay is None:
            return False
        if v.panel is None or not v.composition:
            overlay.hide(self)
            return False
        cfg = self.engine.config
        from ..ui.theme import pick

        overlay.show(self, "decode", v.panel, pick(cfg.panel_theme), cfg.candidate_font_size / 16)
        return True

    def _clear_ui(self, reply: dict, composition: bool = True) -> None:
        overlay = _panel_window(create=False)
        if overlay is not None:
            overlay.hide(self)
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

    def _spontaneous_end(self, app: str) -> bool:
        """The composition ended without the user doing anything: no mouse
        button held, no key just sent to the app, same app as when typing
        started, and an app known to keep a stale composition."""
        cfg = self.engine.config
        if not cfg.keep_on_app_interrupt or app.lower() not in KEEP_APPS:
            return False
        if time.monotonic() - self._passthrough_at < 1.5:
            return False
        if mouse_clicked():
            return False
        return app == self._composing_app

    def _open_settings(self, section: str = "") -> None:
        """Start the settings window (backend\\settings.py) without
        blocking the IME; it is a separate process with its own lifetime."""
        try:
            backend_dir = self.icon_dir.resolve().parents[2]
            script = backend_dir / "settings.py"
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            exe = pythonw if pythonw.is_file() else Path(sys.executable)
            args = [str(exe), str(script)] + ([f"--section={section}"] if section else [])
            subprocess.Popen(args, cwd=str(backend_dir), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True,
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        except Exception:
            log.exception("cannot open the settings window")

    def _update_mode_icon(self, reply: dict, force: bool = False, add: bool = False) -> None:
        mode = self.session.mode
        if not force and mode is self._mode_shown:
            return
        self._mode_shown = mode
        if not self.is_windows8_above:
            return
        name = MODE_ICONS[mode]
        # same file, different spelling: makes PIME load a fresh handle (see _icons_cleared)
        icon = os.path.join(str(self.icon_dir), ".", name) if self._icon_variant else str(self.icon_dir / name)
        button = {
            "id": "windows-mode-icon",
            "icon": icon,
            "tooltip": f"{PRODUCT_NAME}：{self.session.mode_label()}（Shift 切換模式，右鍵選模式）",
            "commandId": ID_MODE_ICON,
            "enable": self.keyboard_open,
        }
        buttons = reply.setdefault("addButton" if add else "changeButton", [])
        buttons[:] = [b for b in buttons if b.get("id") != button["id"]] + [button]
