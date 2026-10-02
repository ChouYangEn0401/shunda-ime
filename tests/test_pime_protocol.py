"""End-to-end: PIME JSON lines in, PIME_MSG replies out."""

import io
import json
from pathlib import Path

from smartime.engine.keys import VK_RETURN
from smartime.pime.server import serve


def key_msg(seq, method, ch="", vk=None):
    states = [0] * 256
    return {
        "method": method,
        "seqNum": seq,
        "charCode": ord(ch) if ch else 0,
        "keyCode": vk if vk is not None else (ord(ch.upper()) if ch.isalnum() else 0),
        "repeatCount": 1,
        "scanCode": 0,
        "isExtended": False,
        "keyStates": states,
    }


def exchange(engine, messages):
    lines = [f"client1|{json.dumps(m, ensure_ascii=False)}\n" for m in messages]
    stdin = io.BytesIO("".join(lines).encode("utf-8"))
    stdout = io.BytesIO()
    serve(stdin, stdout, engine, Path("icons"))
    replies = []
    for line in stdout.getvalue().decode("utf-8").splitlines():
        tag, client, payload = line.split("|", 2)
        assert tag == "PIME_MSG" and client == "client1"
        replies.append(json.loads(payload))
    return replies


def typing(seq_start, text):
    msgs = []
    seq = seq_start
    for ch in text:
        msgs.append(key_msg(seq, "filterKeyDown", ch))
        msgs.append(key_msg(seq + 1, "onKeyDown", ch))
        seq += 2
    return msgs


def test_init_activate_type_commit(engine):
    msgs = [
        {"method": "init", "seqNum": 1, "id": "{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}",
         "isWindows8Above": True, "isMetroApp": False, "isUiLess": False, "isConsole": False},
        {"method": "onActivate", "seqNum": 2, "isKeyboardOpen": True},
        *typing(10, "ji3ap7"),
        key_msg(100, "filterKeyDown", vk=VK_RETURN),
        key_msg(101, "onKeyDown", vk=VK_RETURN),
        {"method": "close"},
    ]
    replies = exchange(engine, msgs)
    by_seq = {r["seqNum"]: r for r in replies}

    assert by_seq[1]["success"] is True
    activate = by_seq[2]
    assert activate["setSelKeys"] == "123456789"
    assert activate["addButton"][0]["id"] == "windows-mode-icon"

    # after "ji3" the composition is 我; after the full input 我們
    assert by_seq[15]["compositionString"] == "我"
    assert by_seq[21]["compositionString"] == "我們"
    assert by_seq[21]["return"] is True

    final = by_seq[101]
    assert final["commitString"] == "我們"
    assert final["compositionString"] == ""


def test_hint_message_is_shown_then_hidden(engine):
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "u.3"),
    ]
    replies = {r["seqNum"]: r for r in exchange(engine, msgs)}
    assert replies[11]["compositionString"] == "u"
    assert replies[13]["showMessage"]["message"] == "ㄧㄡ"  # after "."
    assert "showMessage" in replies[15] or replies[15].get("hideMessage")  # after tone


def test_no_message_in_reply_that_starts_composition(engine):
    # Regression (found with the real TSF typing test): PIME handles
    # showMessage before the composition and, if none exists, ends the
    # temporary composition it opened — committing our first key raw.
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "ji3"),
        {"method": "onCompositionTerminated", "seqNum": 50, "forced": True},  # app ended it
        *typing(60, "u"),
    ]
    replies = {r["seqNum"]: r for r in exchange(engine, msgs)}
    first = replies[11]  # onKeyDown 'j' starts the composition
    assert first["compositionString"] == "j"
    assert "showMessage" not in first
    assert replies[13]["showMessage"]["message"] == "ㄨㄛ"  # composition exists now
    # after the app ended the composition, the next first key again has no message
    assert "showMessage" not in replies[61]


def test_own_commit_termination_keeps_buffer(engine):
    # Regression (VS Code, long sentence): after an automatic partial commit
    # PIME reports onCompositionTerminated(forced=false) for the composition
    # it just ended; the rest of our buffer must survive it.
    engine.config.max_buffer_chars = 2
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "ji3ap7ji3"),  # 3 chars > limit -> 我們 committed, 我 remains
        {"method": "onCompositionTerminated", "seqNum": 50, "forced": False},
        *typing(60, "ap7"),
    ]
    replies = {r["seqNum"]: r for r in exchange(engine, msgs)}
    commits = "".join(r.get("commitString", "") for r in replies.values())
    assert commits == "我們"
    assert replies[65]["compositionString"] == "我們"


def _fake_desktop(monkeypatch, app, mouse=False):
    import smartime.pime.text_service as ts

    monkeypatch.setattr(ts, "foreground_app", lambda: app)
    monkeypatch.setattr(ts, "mouse_clicked", lambda: mouse)


def test_forced_termination_resets_buffer(engine, monkeypatch):
    # a normal app: the text stays in the document, the IME starts over
    _fake_desktop(monkeypatch, "notepad.exe")
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "ji3"),
        {"method": "onCompositionTerminated", "seqNum": 50, "forced": True},
        *typing(60, "u"),
    ]
    replies = {r["seqNum"]: r for r in exchange(engine, msgs)}
    assert replies[61]["compositionString"] == "u"


def test_spontaneous_end_in_a_browser_keeps_the_text(engine, monkeypatch):
    # Chromium editor re-rendered and ended the composition but kept showing
    # it: re-send the whole text so the next update does not erase it
    _fake_desktop(monkeypatch, "msedge.exe")
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "ji3ap7"),
        {"method": "onCompositionTerminated", "seqNum": 50, "forced": True},
        *typing(60, "u"),
    ]
    replies = {r["seqNum"]: r for r in exchange(engine, msgs)}
    assert replies[61]["compositionString"] == "我們u"
    assert "showMessage" not in replies[61]  # the reply that restarts the composition


def test_user_caused_end_in_a_browser_still_resets(engine, monkeypatch):
    # mouse click
    _fake_desktop(monkeypatch, "msedge.exe", mouse=True)
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "ji3"),
        {"method": "onCompositionTerminated", "seqNum": 50, "forced": True},
        *typing(60, "u"),
    ]
    assert {r["seqNum"]: r for r in exchange(engine, msgs)}[61]["compositionString"] == "u"
    # a key sent to the app just before (Ctrl+Enter to send a message): the
    # composition is committed first, then Ctrl+Enter reaches the app
    _fake_desktop(monkeypatch, "msedge.exe")
    ctrl_enter = key_msg(40, "filterKeyDown", vk=VK_RETURN)
    ctrl_enter["keyStates"][0x11] = 0x80
    ctrl_enter_on = dict(ctrl_enter, method="onKeyDown", seqNum=41)
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "ji3"),
        ctrl_enter,
        ctrl_enter_on,
        {"method": "onCompositionTerminated", "seqNum": 50, "forced": True},
        *typing(60, "u"),
    ]
    r = {r["seqNum"]: r for r in exchange(engine, msgs)}
    assert r[40]["return"] is True
    assert r[41]["return"] is False and r[41]["commitString"] == "我"
    assert r[61]["compositionString"] == "u"


def test_unknown_method_and_bad_json_do_not_crash(engine):
    stdin = io.BytesIO(b'c|{"method": "bogus", "seqNum": 7}\nc|not json\n')
    stdout = io.BytesIO()
    serve(stdin, stdout, engine, Path("icons"))
    out = stdout.getvalue().decode("utf-8").splitlines()
    assert len(out) == 2
    assert json.loads(out[0].split("|", 2)[2])["success"] is False
    assert json.loads(out[1].split("|", 2)[2])["success"] is False


def test_tray_menu_lists_the_modes_and_switches(engine):
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        {"method": "onMenu", "seqNum": 2, "id": "windows-mode-icon"},
        {"method": "onCommand", "seqNum": 3, "id": 11, "type": 2},  # 純注音
        {"method": "onMenu", "seqNum": 4, "id": "windows-mode-icon"},
        {"method": "onCommand", "seqNum": 5, "id": 1, "type": 0},  # left click: -> English
    ]
    r = {x["seqNum"]: x for x in exchange(engine, msgs)}
    assert r[1]["addButton"][0]["icon"].endswith("auto.ico")
    menu = r[2]["return"]
    assert [m["text"] for m in menu[:3]] == ["中英自動", "純注音", "純英文"]
    if engine.lexicon.has_pinyin and engine.lexicon.has_cangjie:
        assert [m["text"] for m in menu[3:5]] == ["純拼音", "純倉頡"]
    assert [m["checked"] for m in menu[:3]] == [True, False, False]
    assert r[3]["changeButton"][0]["icon"].endswith("chinese.ico")
    assert [m["checked"] for m in r[4]["return"][:3]] == [False, True, False]
    assert r[5]["changeButton"][0]["icon"].endswith("english.ico")


def exchange_many(engine, lines):
    """[(client_id, message)] -> {(client_id, seqNum): reply}"""
    stdin = io.BytesIO("".join(f"{c}|{json.dumps(m, ensure_ascii=False)}\n" for c, m in lines).encode("utf-8"))
    stdout = io.BytesIO()
    serve(stdin, stdout, engine, Path("C:/PIME/smartime/icons"))
    out = {}
    for line in stdout.getvalue().decode("utf-8").splitlines():
        _, client, payload = line.split("|", 2)
        reply = json.loads(payload)
        out[(client, reply["seqNum"])] = reply
    return out


def test_mode_icon_reloads_after_another_window_deactivates(engine):
    # Regression (自/中/英 icon vanished from the taskbar, or showed a cursor
    # shape): PIME destroys every cached icon of the app process when any of
    # its input contexts deactivates, so the other windows' buttons must be
    # re-sent under a different spelling of the same path to get a new handle.
    import os

    lines = [
        ("a", {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True}),
        ("b", {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True}),
        ("a", key_msg(2, "filterKeyDown", "j")),  # nothing happened yet: no button update
        ("b", {"method": "onDeactivate", "seqNum": 2}),
        ("a", key_msg(3, "filterKeyDown", "j")),
        ("a", key_msg(4, "filterKeyDown", "j")),  # already refreshed
        ("b", {"method": "close"}),
        ("a", key_msg(5, "filterKeyDown", "j")),
    ]
    r = exchange_many(engine, lines)
    first = r[("a", 1)]["addButton"][0]["icon"]
    assert "changeButton" not in r[("a", 2)]
    assert "removeButton" in r[("b", 2)] and "changeButton" not in r[("b", 2)]
    second = r[("a", 3)]["changeButton"][0]["icon"]
    assert second != first and os.path.normpath(second) == os.path.normpath(first)
    assert "changeButton" not in r[("a", 4)]
    third = r[("a", 5)]["changeButton"][0]["icon"]
    assert third == first  # alternates, so the cache key always changes


def _shift_msgs(seq, side):
    """A lone Shift tap as PIME sends it: scanCode 0, the side only in keyStates."""
    from smartime.engine.keys import VK_LSHIFT, VK_RSHIFT, VK_SHIFT

    down = key_msg(seq, "filterKeyDown", vk=VK_SHIFT)
    down["keyStates"][VK_SHIFT] = 0x80
    down["keyStates"][VK_RSHIFT if side == "right" else VK_LSHIFT] = 0x80
    up = key_msg(seq + 1, "filterKeyUp", vk=VK_SHIFT)
    on_up = key_msg(seq + 2, "onKeyUp", vk=VK_SHIFT)
    return [down, up, on_up]


def test_toggle_shift_tells_left_from_right(engine):
    # Regression: PIME sends scanCode 0, so "right Shift only" used to
    # react to the left Shift too.
    engine.config.toggle_shift = "right"
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *_shift_msgs(10, "left"),
        *_shift_msgs(20, "right"),
    ]
    r = {x["seqNum"]: x for x in exchange(engine, msgs)}
    assert r[11]["return"] is False  # left Shift: not a mode toggle
    assert r[21]["return"] is True and r[22]["changeButton"][0]["icon"].endswith("chinese.ico")
    engine.config.toggle_shift = "left"
    r = {x["seqNum"]: x for x in exchange(engine, msgs)}
    assert r[11]["return"] is True and r[21]["return"] is False


def test_click_while_composing_commits_before_the_next_key(engine, monkeypatch):
    # #5: the mouse moved the caret while text was composing (some apps keep
    # the composition open): the next key commits the old text where it was
    # and starts a new composition at the caret.
    import smartime.pime.text_service as ts

    clicks = iter([False, False, False, False, False, False, True])
    monkeypatch.setattr(ts, "mouse_clicked", lambda: next(clicks, False))
    monkeypatch.setattr(ts, "foreground_app", lambda: "notepad.exe")
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "ji3ap7"),  # 6 filterKeyDown calls without a click
        *typing(60, "j"),  # clicked before this key
    ]
    r = {x["seqNum"]: x for x in exchange(engine, msgs)}
    assert r[61]["commitString"] == "我們"
    assert r[61]["compositionString"] == "j"
    assert "showMessage" not in r[61]  # this reply starts a new composition
