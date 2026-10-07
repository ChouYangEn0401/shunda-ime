"""Settings app HTTP API (runs a real server on 127.0.0.1)."""

import json
import threading
import urllib.error
import urllib.request

import pytest

import smartime
from smartime import paths
from smartime.config import Config
from smartime.settings.api import SettingsApp, SettingsServer

TOKEN = "test-token"


@pytest.fixture
def server():
    app = SettingsApp()
    srv = SettingsServer(app, TOKEN)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    app.close()


def call(srv, method, path, body=None, token=TOKEN, raw=None, host=None):
    url = f"http://127.0.0.1:{srv.port}{path}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("X-SmartIME-Token", token)
    if host:
        req.add_header("Host", host)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            return resp.status, (json.loads(payload) if "json" in ctype else payload)
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, json.loads(payload) if payload.startswith(b"{") else payload


def test_api_requires_token_and_local_host(server):
    assert call(server, "GET", "/api/state", token=None)[0] == 403
    assert call(server, "GET", "/api/state", token="wrong")[0] == 403
    assert call(server, "GET", "/api/state", host="evil.example")[0] == 403
    status, state = call(server, "GET", "/api/state")
    assert status == 200 and state["config"]["start_mode"] == "auto"


def test_static_files_and_no_path_traversal(server):
    status, page = call(server, "GET", "/", token=None)
    assert status == 200 and smartime.PRODUCT_NAME.encode() in page
    assert call(server, "GET", "/../api.py", token=None)[0] == 404
    assert call(server, "GET", "/%2e%2e/api.py", token=None)[0] == 404


def test_save_config_is_validated_and_written(server):
    status, cfg = call(server, "POST", "/api/config",
                       {"start_mode": "chinese", "candidates_per_page": 99, "learn": "yes", "bogus": 1})
    assert status == 200
    assert cfg["start_mode"] == "chinese"
    assert cfg["candidates_per_page"] == 9  # clamped
    assert cfg["learn"] is True  # wrong type ignored
    assert Config.load(paths.config_path()).start_mode == "chinese"


def test_inbox_and_my_words_are_separate_views(server):
    app = server.app
    app.user.learn("逗號", "ㄉㄡˋ-ㄏㄠˋ", origin="fix")
    app.user.learn("我們", "ㄨㄛˇ-ㄇㄣ˙")
    app.user.learn("我們", "ㄨㄛˇ-ㄇㄣ˙")
    call(server, "POST", "/api/entries", {"phrase": "陳怡君", "category": "朋友"})
    status, page = call(server, "GET", "/api/entries?view=inbox&sort=count&paged=1")
    assert status == 200 and page["total"] == 2
    assert [r["phrase"] for r in page["rows"]] == ["我們", "逗號"]
    assert page["rows"][1]["origin"] == "fix"
    status, page = call(server, "GET", "/api/entries?view=inbox&paged=1&limit=1&offset=1&sort=count")
    assert [r["phrase"] for r in page["rows"]] == ["逗號"] and page["total"] == 2
    status, page = call(server, "GET", "/api/entries?view=mine&paged=1")
    assert [r["phrase"] for r in page["rows"]] == ["陳怡君"]
    # tagging an inbox word moves it to my words
    inbox_id = [r for r in call(server, "GET", "/api/entries?view=inbox")[1] if r["phrase"] == "逗號"][0]["id"]
    assert call(server, "PATCH", f"/api/entries/{inbox_id}", {"category": "常用詞"})[0] == 200
    assert call(server, "GET", "/api/entries?view=inbox&paged=1")[1]["total"] == 1
    assert call(server, "GET", "/api/entries?view=mine&category=%E5%B8%B8%E7%94%A8%E8%A9%9E&paged=1")[1]["total"] == 1
    stats = call(server, "GET", "/api/state")[1]["stats"]
    assert stats["inbox"] == 1 and stats["mine"] == 2


def test_snippets_add_edit_reorder_delete(server):
    status, a = call(server, "POST", "/api/snippets", {"title": "我的地址", "keyword": "addr", "body": "台北市\n大安區"})
    assert status == 200
    _, b = call(server, "POST", "/api/snippets", {"body": "感謝您的來信"})
    assert call(server, "POST", "/api/snippets", {"body": "   "})[0] == 400
    rows = call(server, "GET", "/api/snippets")[1]
    assert [r["id"] for r in rows] == [a["id"], b["id"]] and rows[0]["body"] == "台北市\n大安區"
    assert call(server, "PATCH", f"/api/snippets/{b['id']}", {"move": -1})[0] == 200
    assert [r["id"] for r in call(server, "GET", "/api/snippets")[1]] == [b["id"], a["id"]]
    assert call(server, "PATCH", f"/api/snippets/{a['id']}", {"keyword": "home"})[0] == 200
    assert call(server, "PATCH", f"/api/snippets/{a['id']}", {"body": ""})[0] == 400
    assert server.app.user.snippets("ho")[0]["id"] == a["id"]
    assert call(server, "DELETE", f"/api/snippets/{b['id']}")[0] == 200
    assert [r["id"] for r in call(server, "GET", "/api/snippets")[1]] == [a["id"]]


def test_add_list_move_and_delete_entries(server):
    status, r = call(server, "POST", "/api/reading", {"text": "陳怡君"})
    assert status == 200 and r["kind"] == "zh" and len(r["reading"].split()) == 3
    status, added = call(server, "POST", "/api/entries", {"phrase": "陳怡君", "reading": "", "category": "朋友"})
    assert status == 200
    status, rows = call(server, "GET", "/api/entries?view=%E6%9C%8B%E5%8F%8B")  # 朋友
    assert [x["phrase"] for x in rows] == ["陳怡君"]
    assert call(server, "PATCH", f"/api/entries/{added['id']}", {"category": "常用詞"})[0] == 200
    status, rows = call(server, "GET", "/api/entries?view=%E5%B8%B8%E7%94%A8%E8%A9%9E")  # 常用詞
    assert rows[0]["category"] == "常用詞"
    assert call(server, "DELETE", f"/api/entries/{added['id']}")[0] == 200
    assert call(server, "GET", "/api/entries")[1] == []


def test_entry_validation_messages(server):
    status, err = call(server, "POST", "/api/entries", {"phrase": "陳怡君", "reading": "ㄔㄣˊ ㄧˊ"})
    assert status == 400 and "3 個字" in err["error"]
    status, err = call(server, "POST", "/api/entries", {"phrase": "怡君", "reading": "ㄔㄣˊ abc"})
    assert status == 400
    status, _ = call(server, "POST", "/api/entries", {"phrase": "vscode"})
    assert status == 200
    rows = call(server, "GET", "/api/entries")[1]
    assert rows[0]["kind"] == "en" and rows[0]["category"] == "常用英文"


def test_categories(server):
    status, r = call(server, "POST", "/api/categories", {"name": "公司同事"})
    assert status == 200
    assert call(server, "POST", "/api/categories", {"name": "公司同事"})[0] == 400
    names = [c["name"] for c in call(server, "GET", "/api/state")[1]["categories"]]
    assert "公司同事" in names
    assert call(server, "DELETE", f"/api/categories/{r['id']}")[0] == 200


def test_export_then_import_merges(server):
    call(server, "POST", "/api/entries", {"phrase": "林志豪", "category": "朋友"})
    status, blob = call(server, "GET", "/api/export")
    assert status == 200 and blob[:2] == b"PK"
    call(server, "POST", "/api/clear-learned")
    rows = call(server, "GET", "/api/entries")[1]
    call(server, "DELETE", f"/api/entries/{rows[0]['id']}")
    status, r = call(server, "POST", "/api/import?settings=0", raw=blob)
    assert status == 200 and r["merged"] == 1
    assert [x["phrase"] for x in call(server, "GET", "/api/entries")[1]] == ["林志豪"]
    assert call(server, "POST", "/api/import?settings=0", raw=b"not a file")[0] == 400


def test_tidy_memory_reports_size(server):
    status, body = call(server, "POST", "/api/memory/tidy")
    assert status == 200 and body["removed"] == 0
    assert body["stats"]["bytes"] > 0


def test_update_state_reads_the_cache_without_going_online(monkeypatch):
    """The settings page must open instantly and work offline; only the
    「檢查更新」 button is allowed to make a request."""
    from smartime import update as upd

    app = SettingsApp()
    calls = []
    monkeypatch.setattr(upd, "check", lambda force=True: calls.append(force) or upd.Release())
    state = app.update_state()
    assert calls == [] and state["current"] and state["latest"] == ""
    app.update_state(force=True)
    assert calls == [True]
    app.close()


def test_version_comparison():
    from smartime import update as upd

    v = upd.version_tuple
    assert v("v0.10.0") > v("0.9.9")
    # a release is newer than every pre-release of itself, and a pre-release
    # of the next version is newer than the one before it
    assert v("0.8.0-alpha.3") < v("0.8.0-rc.1") < v("0.8.0")
    assert v("0.7.0") < v("0.8.0-alpha.1")
    assert not upd.Release(version="0.0.1").newer
    assert upd.Release(version="99.0.0").newer
