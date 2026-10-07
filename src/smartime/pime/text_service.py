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
from .winapp import KEEP_APPS, foreground_app, foreground_elevated, mouse_clicked, send_key_again

log = logging.getLogger(__name__)

ID_MODE_ICON = 1  # left click on the tray icon: same as a Shift tap
ID_ABOUT = 3
ID_SETTINGS = 4
# Right-click menu entries for the three modes.
MODE_MENU_IDS = {10: Mode.AUTO, 11: Mode.CHINESE, 12: Mode.ENGLISH, 13: Mode.PINYIN, 14: Mode.CANGJIE}

# The rest of the tray menu. 華碩智慧輸入法 puts the settings people actually
# flip (自動完成字, 輸入中顯示注音, 字元寬度, 鍵盤配置, 主題顏色) straight into
# this menu with submenus, and keeps one 教學與設定 entry for everything else;
# Windows' own IMEs do much the same. Ours used to be three modes plus
# 設定…, so changing anything meant opening a window and finding the page.
# These are the switches worth reaching in one click, plus a way into the
# page that owns each of the longer lists.
ID_SETTINGS_PUNCT, ID_SETTINGS_DICT, ID_SETTINGS_KEYS = 5, 6, 7
ID_UPDATE = 8
TOGGLES = {  # id: (config field, label)
    20: ("autocomplete", "接續建議（Tab 接詞）"),
    21: ("composing_indicator", "組字中顯示小點"),
    22: ("learn_notice", "學到新詞時通知我"),
    23: ("correction_mode", "Esc 進修正模式"),
    24: ("smart_suggest", "超智慧推薦（實驗）"),
    25: ("crazy_mode", "瘋狂模式（實驗）"),
}
# id: (config field, value, label), grouped into submenus by the first entry
CHOICES = {
    30: ("panel_decode", "off", "關閉"),
    31: ("panel_decode", "correction", "只在修正模式"),
    32: ("panel_decode", "always", "一直顯示"),
    35: ("panel_theme", "system", "跟隨系統"),
    36: ("panel_theme", "light", "淺色"),
    37: ("panel_theme", "dark", "深色"),
    40: ("chinese_scheme", "zhuyin", "注音"),
    41: ("chinese_scheme", "pinyin", "拼音"),
    42: ("chinese_scheme", "cangjie", "倉頡五代"),
}
SUBMENUS = [("解碼面板", (30, 31, 32)), ("面板顏色", (35, 36, 37)), ("中英自動裡的中文", (40, 41, 42))]
MODE_ICONS = {Mode.AUTO: "auto.ico", Mode.CHINESE: "chinese.ico", Mode.ENGLISH: "english.ico",
              Mode.PINYIN: "pinyin.ico", Mode.CANGJIE: "cangjie.ico"}

MESSAGE_DURATION = 3600  # seconds; we hide the message explicitly
# What we put in PIME's own message window when we draw the hint ourselves.
# The window has to exist: PIME places it right under the caret and moves it
# on every composition update, which is how this process learns where the
# text is (TSF's GetTextExt lives in the application's process). One space
# makes it as small as it goes; smartime.ui.overlay then makes it invisible
# and puts our own strip in its place.
ANCHOR_MESSAGE = " "
SELECTION_KEYS = "123456789"
SETTINGS_SECTIONS = {ID_SETTINGS: "", ID_ABOUT: "about", ID_SETTINGS_PUNCT: "punct",
                     ID_SETTINGS_DICT: "dict", ID_SETTINGS_KEYS: "keys", ID_UPDATE: "about"}


def _panel_window(create: bool, second: bool = False):
    """A panel window (smartime.ui.overlay), or None where it cannot exist."""
    try:
        from ..ui import overlay
    except Exception:  # noqa: BLE001 - not on Windows, or a broken install: plain PIME windows
        return None
    if second:
        return overlay.get_second() if create else overlay._second
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
            key = key_from_msg(msg)
            ret = self.keyboard_open and s.key_down(key)
            back = s.take_hand_back()
            if back is not None and self._send_again(back):
                # committed, and the key typed again for the app: the original
                # is taken (apps on the IMM32 compatibility layer have already
                # lost it once the IME claimed it), the copy arrives after
                # the commit and passes straight through
                ret = True
            if not ret or back is not None:
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
            elif command in SETTINGS_SECTIONS:
                self._open_settings(SETTINGS_SECTIONS[command])
            elif command in TOGGLES:
                field, _ = TOGGLES[command]
                self._set_config(field, not getattr(self.engine.config, field))
            elif command in CHOICES:
                field, value, _ = CHOICES[command]
                self._set_config(field, value)
            self._render(reply)
        elif method == "onMenu":
            ret = self._menu()
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

        panel_kind = self._panel_kind(v)
        if v.candidates is not None and panel_kind != "candidates":
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
        self._show_smart(v)
        shown = self._show_panel(v, panel_kind)
        if shown and not self._showing_candidates:
            # Our own panel says all of this, in our own colours. PIME's
            # window stays alive underneath purely as the anchor, with one
            # space in it, so it is created once per composition instead of
            # being destroyed and rebuilt on every keystroke (which is what
            # made the yellow box blink).
            message = ANCHOR_MESSAGE
        elif shown == "decode" and v.correcting and not v.notice:
            message = "修正模式 · Esc 回到打字"
        elif panel_kind == "candidates" and not v.notice:
            message = ("符號 · Esc 關閉" if v.candidate_panel.palette else
                       "片語 · Enter 打出" if v.candidate_panel.snippet else "選字 · Esc 取消")
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

    def _show_smart(self, v) -> None:
        """超智慧推薦 (experimental) in a second window under the first."""
        want = v.smart_panel is not None and bool(v.composition) and v.candidates is None
        overlay = _panel_window(create=want, second=True)
        if overlay is None:
            return
        if not want:
            overlay.hide(self)
            return
        cfg = self.engine.config
        from ..ui.theme import pick

        overlay.show(self, "smart", v.smart_panel, pick(cfg.panel_theme), cfg.candidate_font_size / 16)

    def _panel_kind(self, v) -> str:
        """Which of our panels this view wants: "candidates", "decode" or "".
        Our panels dock under PIME's hint box, which needs a composition;
        with nothing composed (symbol panel from idle) PIME's own list is used."""
        if not v.composition:
            return ""
        cfg = self.engine.config
        if v.candidate_panel is not None and cfg.panel_candidates:
            return "candidates" if _panel_window(create=True) is not None else ""
        if v.panel is not None:
            return "decode"
        if v.hint_panel is not None and cfg.panel_hint:
            return "hint" if _panel_window(create=True) is not None else ""
        return ""

    def _show_panel(self, v, kind: str) -> str:
        """Show / hide our own panel window for this view; returns the kind shown."""
        overlay = _panel_window(create=bool(kind))
        if overlay is None:
            return ""
        if not kind:
            overlay.hide(self)
            return ""
        cfg = self.engine.config
        from ..ui.theme import pick

        model = {"candidates": v.candidate_panel, "decode": v.panel, "hint": v.hint_panel}[kind]
        overlay.show(self, kind, model, pick(cfg.panel_theme), cfg.candidate_font_size / 16,
                     cover=not self._showing_candidates)
        return kind

    def _clear_ui(self, reply: dict, composition: bool = True) -> None:
        for second in (False, True):
            overlay = _panel_window(create=False, second=second)
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

    def _send_again(self, key: KeyInput) -> bool:
        """Type ``key`` again for the app (False: let the original through)."""
        if foreground_elevated():
            return False  # Windows blocks our input there; TSF passes the original
        try:
            return send_key_again(key.vk, key.char, key.ctrl, key.shift, key.extended)
        except Exception:  # noqa: BLE001 - never break typing
            log.exception("cannot send the key again")
            return False

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

    def _menu(self) -> list[dict]:
        """The tray icon's right-click menu."""
        s, cfg = self.session, self.engine.config
        # every mode this lexicon supports, Shift cycle or not
        items: list[dict] = [
            {"text": s.mode_label() if mode is Mode.AUTO else mode.label, "id": cid, "checked": s.mode is mode}
            for cid, mode in MODE_MENU_IDS.items() if s._available(mode)
        ]
        items.append({})
        items += [{"text": label, "id": cid, "checked": bool(getattr(cfg, field, False))}
                  for cid, (field, label) in TOGGLES.items()]
        for title, ids in SUBMENUS:
            field = CHOICES[ids[0]][0]
            now = getattr(cfg, field, None)
            sub = [{"text": CHOICES[i][2], "id": i, "checked": CHOICES[i][1] == now} for i in ids]
            here = next((c[2] for c in (CHOICES[i] for i in ids) if c[1] == now), "")
            items.append({"text": f"{title}（{here}）" if here else title, "submenu": sub})
        items.append({})
        items += [{"text": "標點與符號…", "id": ID_SETTINGS_PUNCT},
                  {"text": "我的詞庫…", "id": ID_SETTINGS_DICT},
                  {"text": "按鍵說明…", "id": ID_SETTINGS_KEYS},
                  {"text": "設定…", "id": ID_SETTINGS},
                  {},
                  {"text": "檢查更新…", "id": ID_UPDATE},
                  {"text": f"關於{PRODUCT_NAME}", "id": ID_ABOUT}]
        return items

    def _set_config(self, field: str, value) -> None:
        """Flip a setting from the tray menu and write it out, so the
        settings window and the next backend start agree with what the user
        just chose."""
        cfg = self.engine.config
        setattr(cfg, field, value)
        cfg._normalize()
        if field in ("chinese_scheme", "crazy_mode", "smart_suggest"):
            self.engine.decoder.apply_config(cfg)
        try:
            cfg.save(self.engine.config_path)
        except Exception:
            log.exception("cannot save the setting changed from the tray menu")

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
