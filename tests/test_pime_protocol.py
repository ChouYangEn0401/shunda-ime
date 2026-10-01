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


def test_forced_termination_resets_buffer(engine):
    msgs = [
        {"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True},
        *typing(10, "ji3"),
        {"method": "onCompositionTerminated", "seqNum": 50, "forced": True},
        *typing(60, "u"),
    ]
    replies = {r["seqNum"]: r for r in exchange(engine, msgs)}
    assert replies[61]["compositionString"] == "u"


def test_unknown_method_and_bad_json_do_not_crash(engine):
    stdin = io.BytesIO(b'c|{"method": "bogus", "seqNum": 7}\nc|not json\n')
    stdout = io.BytesIO()
    serve(stdin, stdout, engine, Path("icons"))
    out = stdout.getvalue().decode("utf-8").splitlines()
    assert len(out) == 2
    assert json.loads(out[0].split("|", 2)[2])["success"] is False
    assert json.loads(out[1].split("|", 2)[2])["success"] is False
