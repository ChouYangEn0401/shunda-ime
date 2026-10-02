"""Settings app backend: a tiny local HTTP API (standard library only).

The page (ui/index.html) runs in an Edge/Chrome app window and talks to this
server on 127.0.0.1. Every API call must carry the per-launch token (header
``X-SmartIME-Token``) and a Host of 127.0.0.1, so other web pages and DNS
rebinding cannot reach it.

Changes are written where the IME reads them: config.json (reloaded on the
next keystroke) and user.db (noticed through SQLite's data_version).
"""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import PRODUCT_NAME, __version__, paths
from ..config import Config
from ..engine.lexicon import Lexicon
from ..engine.userdict import UserDict
from ..voice import launch as voice_launch
from ..voice import models as voice_models

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parent / "ui"
EXPORT_NAME = "我的記憶.smartime"
MAX_UPLOAD = 50 * 1024 * 1024
_READING_RE = re.compile(r"^[\u3105-\u3129\u02ca\u02c7\u02cb\u02d9]+(-[\u3105-\u3129\u02ca\u02c7\u02cb\u02d9]+)*$")


def pime_dir() -> Path:
    return Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "PIME"


def pime_log_config() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "PIME" / "PIMELauncher.json"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class SettingsApp:
    """All operations behind the API; kept separate from HTTP for testing."""

    def __init__(self, system_db: Path | None = None):
        self.config_path = paths.config_path()
        self.user = UserDict(paths.user_db_path())
        self.lexicon = Lexicon(system_db or paths.system_db_path())
        self.valid_syllables = self.lexicon.valid_syllables
        self.last_ping = time.monotonic()
        self.download: dict = {}  # voice model download progress
        self.install_state: dict = {}  # voice component installation

    def close(self) -> None:
        self.user.close()
        self.lexicon.close()

    # ---------------------------------------------------------- state
    def state(self) -> dict:
        return {
            "product": PRODUCT_NAME,
            "version": __version__,
            "config": Config.load(self.config_path).to_dict(),
            "defaults": Config().to_dict(),
            "categories": self.user.categories(),
            "stats": self.user.stats(),
            "userDir": str(paths.user_dir()),
            "debugLog": self.debug_log_state(),
            "punct": self.punct_info(),
        }

    @staticmethod
    def punct_info() -> dict:
        """What the punctuation table needs: the symbol keys, their
        full-width forms and the default Ctrl / Ctrl+Shift outputs."""
        from ..engine import punct
        from ..engine.decoder import FULLWIDTH_PUNCT

        return {
            "keycaps": [[lower, upper] for _, lower, upper in punct.KEYCAPS],
            "fullwidth": FULLWIDTH_PUNCT,
            "ctrl": {punct.combo_name(lower, shift): out for (lower, shift), out in punct.CTRL_PUNCT.items()},
        }

    # ---------------------------------------------------------- config
    def save_config(self, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise ApiError(400, "設定格式不正確")
        current = Config.load(self.config_path)
        new = Config.from_dict(patch, base=current)
        new.save(self.config_path)
        if patch.get("voice_enabled") is True:
            voice_launch.start()  # the service exits by itself when turned off
        return new.to_dict()

    # ---------------------------------------------------------- voice input
    def busy(self) -> bool:
        """A background job that must not be cut off by the idle exit."""
        return bool(self.download.get("active") or self.install_state.get("active"))

    def voice_state(self) -> dict:
        py = voice_launch.voice_python()
        running = voice_launch.running()
        status = {}
        if running:
            try:
                status = json.loads((paths.user_dir() / "voice-status.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                status = {"state": "loading"}
        return {
            "status": status,
            "models": voice_models.status(),
            "runtime": bool(py),
            "running": running,
            "download": dict(self.download),
            "install": dict(self.install_state, log=list(self.install_state.get("log", []))[-8:]),
        }

    def install_voice(self) -> dict:
        if self.install_state.get("active"):
            raise ApiError(400, "已經在安裝了")
        from ..voice import install as voice_install

        self.install_state = {"active": True, "log": [], "error": ""}

        def run() -> None:
            try:
                voice_install.install(lambda line: self.install_state["log"].append(line))
            except Exception as e:  # noqa: BLE001
                log.exception("voice component installation failed")
                self.install_state["error"] = str(e)
            self.install_state["active"] = False

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def start_download(self, key: str) -> dict:
        if key not in voice_models.MODELS:
            raise ApiError(400, "沒有這個模型")
        if self.download.get("active"):
            raise ApiError(400, "已經在下載了")
        self.download = {"key": key, "done": 0, "total": 0, "active": True, "error": ""}

        def run() -> None:
            def progress(done: int, total: int) -> None:
                self.download.update(done=done, total=total)

            try:
                voice_models.download(key, progress)
            except Exception as e:  # noqa: BLE001
                log.exception("model download failed")
                self.download["error"] = str(e)
            self.download["active"] = False

        threading.Thread(target=run, daemon=True).start()
        return dict(self.download)

    def reset_config(self) -> dict:
        cfg = Config()
        cfg.save(self.config_path)
        return cfg.to_dict()

    # ---------------------------------------------------------- dictionary
    def entries(self, query: dict) -> list[dict] | dict:
        """view: inbox (自動收集) | mine (我的詞庫, optionally ``category``) |
        blocked, or the older "", "learned", <category name>. sort: recent |
        count. With paged=1: {"rows": [...], "total": n} for ``offset``/``limit``."""
        def one(key: str) -> str:
            return (query.get(key) or [""])[0]

        view = one("view")
        kwargs: dict = {"query": one("q").strip()}
        if view in ("inbox", "mine", "blocked"):
            kwargs["view"] = view
            if view == "mine" and one("category"):
                kwargs["category"] = one("category")
        elif view == "learned":
            kwargs.update(source="learned", blocked=False)
        else:
            kwargs.update(blocked=False)
            if view:
                kwargs["category"] = view
        try:
            offset = max(0, int(one("offset") or 0))
            limit = max(1, min(1000, int(one("limit") or 500)))
        except ValueError as e:
            raise ApiError(400, "分頁參數不正確") from e
        sort = one("sort") or ("recent" if view in ("inbox", "mine", "blocked") else "default")
        rows = self.user.list(sort=sort, offset=offset, limit=limit, **kwargs)
        for r in rows:
            r["readingDisplay"] = r["reading"].replace("-", " ")
        if one("paged") == "1":
            return {"rows": rows, "total": self.user.count(**kwargs)}
        return rows

    def suggest_reading(self, text: str) -> dict:
        text = text.strip()
        if not text:
            return {"kind": "zh", "reading": "", "chars": []}
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .'+#-]*", text):
            return {"kind": "en", "reading": "", "chars": []}
        reading = self.lexicon.reading_for(text)
        chars = [{"char": ch, "readings": self.lexicon.readings_of_char(ch)} for ch in text]
        return {"kind": "zh", "reading": (reading or "").replace("-", " "), "chars": chars}

    def _normalize_reading(self, phrase: str, reading: str) -> str:
        reading = "-".join(reading.replace("　", " ").split())
        if not reading:
            auto = self.lexicon.reading_for(phrase)
            if auto is None:
                raise ApiError(400, f"找不到「{phrase}」的注音，請手動輸入（音節之間用空白分開）")
            reading = auto
        if not _READING_RE.match(reading):
            raise ApiError(400, "注音只能包含注音符號與聲調，音節之間用空白分開")
        syllables = reading.split("-")
        if len(syllables) != len(phrase):
            raise ApiError(400, f"「{phrase}」有 {len(phrase)} 個字，但注音有 {len(syllables)} 個音節")
        bad = [s for s in syllables if s not in self.valid_syllables]
        if bad:
            raise ApiError(400, f"不是有效的注音：{' '.join(bad)}")
        return reading

    def add_entry(self, body: dict) -> dict:
        phrase = str(body.get("phrase", "")).strip()
        if not phrase:
            raise ApiError(400, "請輸入要加入的詞")
        category = str(body.get("category", "")).strip() or None
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .'+#-]*", phrase):
            entry_id = self.user.add(phrase.lower(), "", "en", category or "常用英文")
        else:
            reading = self._normalize_reading(phrase, str(body.get("reading", "")))
            entry_id = self.user.add(phrase, reading, "zh", category)
        return {"id": entry_id}

    def update_entry(self, entry_id: int, body: dict) -> dict:
        kwargs = {}
        if "category" in body:
            kwargs["category"] = str(body["category"])
        if "blocked" in body:
            kwargs["blocked"] = bool(body["blocked"])
        if "reading" in body:
            row = [r for r in self.user.list(limit=100000) if r["id"] == entry_id]
            if not row:
                raise ApiError(404, "找不到這個詞")
            kwargs["reading"] = self._normalize_reading(row[0]["phrase"], str(body["reading"]))
        self.user.update(entry_id, **kwargs)
        return {"ok": True}

    def delete_entry(self, entry_id: int) -> dict:
        self.user.delete(entry_id)
        return {"ok": True}

    def add_category(self, body: dict) -> dict:
        name = str(body.get("name", "")).strip()
        if not name:
            raise ApiError(400, "請輸入分類名稱")
        if any(c["name"] == name for c in self.user.categories()):
            raise ApiError(400, f"已經有「{name}」這個分類")
        return {"id": self.user.add_category(name)}

    def rename_category(self, cat_id: int, body: dict) -> dict:
        name = str(body.get("name", "")).strip()
        if not name:
            raise ApiError(400, "請輸入分類名稱")
        self.user.rename_category(cat_id, name)
        return {"ok": True}

    def delete_category(self, cat_id: int) -> dict:
        self.user.delete_category(cat_id)
        return {"ok": True}

    # ---------------------------------------------------------- snippets (片語)
    def snippets(self) -> list[dict]:
        return self.user.snippets()

    def add_snippet(self, body: dict) -> dict:
        text = str(body.get("body", ""))
        if not text.strip():
            raise ApiError(400, "請輸入片語的內容")
        if len(text) > 4000:
            raise ApiError(400, "片語太長（最多 4000 字）")
        return {"id": self.user.add_snippet(text, str(body.get("title", ""))[:40], str(body.get("keyword", ""))[:20])}

    def update_snippet(self, snippet_id: int, body: dict) -> dict:
        if "move" in body:
            self.user.move_snippet(snippet_id, -1 if int(body["move"]) < 0 else 1)
        fields = {k: body[k] for k in ("title", "keyword", "body") if k in body}
        if "body" in fields and not str(fields["body"]).strip():
            raise ApiError(400, "片語的內容不能是空的")
        try:
            self.user.update_snippet(snippet_id, **fields)
        except ValueError as e:
            raise ApiError(400, str(e)) from e
        return {"ok": True}

    def delete_snippet(self, snippet_id: int) -> dict:
        self.user.delete_snippet(snippet_id)
        return {"ok": True}

    def clear_learned(self) -> dict:
        return {"removed": self.user.clear_learned()}

    def tidy_memory(self) -> dict:
        removed = self.user.tidy(compact=True)
        return {"removed": removed, "stats": self.user.stats()}

    # ---------------------------------------------------------- export / import
    def export_bundle(self) -> bytes:
        """A zip with user.db (consistent snapshot) and config.json."""
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "user.db"
            self.user.backup_to(db)
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(db, "user.db")
                if self.config_path.exists():
                    z.write(self.config_path, "config.json")
                z.writestr("README.txt", f"{PRODUCT_NAME} {__version__} 的「我的記憶」匯出檔。"
                                         "在另一台電腦的設定頁 > 資料與隱私 > 匯入。\n")
        return buf.getvalue()

    def import_bundle(self, data: bytes, with_settings: bool) -> dict:
        if len(data) > MAX_UPLOAD:
            raise ApiError(400, "檔案太大")
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "user.db"
            config_data = None
            if data[:2] == b"PK":
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        names = z.namelist()
                        if "user.db" not in names:
                            raise ApiError(400, f"這不是{PRODUCT_NAME}的匯出檔（缺少 user.db）")
                        db.write_bytes(z.read("user.db"))
                        if "config.json" in names:
                            config_data = z.read("config.json")
                except zipfile.BadZipFile as e:
                    raise ApiError(400, "檔案損壞，無法讀取") from e
            elif data[:16] == b"SQLite format 3\x00":
                db.write_bytes(data)
            else:
                raise ApiError(400, f"這不是{PRODUCT_NAME}的匯出檔")
            try:
                merged = self.user.merge_from(db)
            except sqlite3.DatabaseError as e:
                raise ApiError(400, f"無法讀取詞庫：{e}") from e
        applied = False
        if with_settings and config_data:
            try:
                cfg = Config.from_dict(json.loads(config_data.decode("utf-8")))
            except (ValueError, UnicodeDecodeError) as e:
                raise ApiError(400, "設定檔格式不正確") from e
            cfg.save(self.config_path)
            applied = True
        return {"merged": merged, "settingsApplied": applied}

    # ---------------------------------------------------------- system
    def open_folder(self) -> dict:
        os.startfile(paths.user_dir())  # noqa: S606 - opening the user's own folder
        return {"ok": True}

    def debug_log_state(self) -> dict:
        try:
            level = json.loads(pime_log_config().read_text(encoding="utf-8")).get("logLevel", "info")
        except (OSError, ValueError):
            level = "info"
        return {"on": level in ("debug", "trace"), "level": level, "path": str(pime_log_config().parent / "Log")}

    def set_debug_log(self, on: bool) -> dict:
        """PIMELauncher reads its log level at start, so restart it."""
        path = pime_log_config()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"logLevel": "debug" if on else "warn"}, indent=1), encoding="utf-8")
        launcher = pime_dir() / "PIMELauncher.exe"
        if launcher.exists():
            subprocess.run([str(launcher), "/quit"], timeout=15)
            time.sleep(0.8)
            subprocess.Popen([str(launcher)], creationflags=subprocess.DETACHED_PROCESS, close_fds=True)
        return self.debug_log_state()


class _Handler(BaseHTTPRequestHandler):
    server: "SettingsServer"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep stdout quiet; use logging
        log.debug("http: " + fmt, *args)

    # ---------------------------------------------------------- plumbing
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise ApiError(400, "檔案太大")
        return self.rfile.read(n) if n else b""

    def _json_body(self) -> dict:
        raw = self._body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ApiError(400, "請求格式不正確") from e
        if not isinstance(data, dict):
            raise ApiError(400, "請求格式不正確")
        return data

    def _authorized(self, query: dict) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        token = self.headers.get("X-SmartIME-Token") or (query.get("t") or [""])[0]
        return token == self.server.token

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        path = url.path
        try:
            if not path.startswith("/api/"):
                if method != "GET":
                    raise ApiError(405, "not allowed")
                return self._static(path)
            if not self._authorized(query):
                raise ApiError(403, "forbidden")
            app = self.server.app
            app.last_ping = time.monotonic()
            with self.server.lock:
                result = self._route(app, method, path, query)
            if isinstance(result, tuple):  # (bytes, content type, headers)
                self._send(200, *result)
            else:
                self._json(200, result)
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 - report instead of dropping the connection
            log.exception("settings API error")
            self._json(500, {"error": f"發生錯誤：{e}"})

    def _route(self, app: SettingsApp, method: str, path: str, query: dict):
        m = re.fullmatch(r"/api/(entries|categories|snippets)/(\d+)", path)
        if m:
            kind, ident = m.group(1), int(m.group(2))
            if kind == "snippets":
                if method == "PATCH":
                    return app.update_snippet(ident, self._json_body())
                if method == "DELETE":
                    return app.delete_snippet(ident)
            elif kind == "entries":
                if method == "PATCH":
                    return app.update_entry(ident, self._json_body())
                if method == "DELETE":
                    return app.delete_entry(ident)
            else:
                if method == "PATCH":
                    return app.rename_category(ident, self._json_body())
                if method == "DELETE":
                    return app.delete_category(ident)
            raise ApiError(405, "not allowed")
        routes = {
            ("GET", "/api/ping"): lambda: {"ok": True},
            ("GET", "/api/state"): app.state,
            ("POST", "/api/config"): lambda: app.save_config(self._json_body()),
            ("POST", "/api/config/reset"): app.reset_config,
            ("GET", "/api/entries"): lambda: app.entries(query),
            ("POST", "/api/entries"): lambda: app.add_entry(self._json_body()),
            ("POST", "/api/reading"): lambda: app.suggest_reading(str(self._json_body().get("text", ""))),
            ("POST", "/api/categories"): lambda: app.add_category(self._json_body()),
            ("GET", "/api/snippets"): app.snippets,
            ("POST", "/api/snippets"): lambda: app.add_snippet(self._json_body()),
            ("POST", "/api/clear-learned"): app.clear_learned,
            ("POST", "/api/memory/tidy"): app.tidy_memory,
            ("POST", "/api/open-folder"): app.open_folder,
            ("POST", "/api/debug-log"): lambda: app.set_debug_log(bool(self._json_body().get("on"))),
            ("GET", "/api/voice"): app.voice_state,
            ("POST", "/api/voice/download"): lambda: app.start_download(str(self._json_body().get("key", ""))),
            ("POST", "/api/voice/install"): app.install_voice,
            ("GET", "/api/export"): lambda: (
                app.export_bundle(), "application/zip",
                {"Content-Disposition": "attachment; filename*=UTF-8''%E6%88%91%E7%9A%84%E8%A8%98%E6%86%B6.smartime"},
            ),
            ("POST", "/api/import"): lambda: app.import_bundle(
                self._body(), (query.get("settings") or ["0"])[0] == "1"),
        }
        handler = routes.get((method, path))
        if handler is None:
            raise ApiError(404, "not found")
        return handler()

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        target = (UI_DIR / path.lstrip("/")).resolve()
        if UI_DIR not in target.parents or not target.is_file():
            raise ApiError(404, "not found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype, {
            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:",
        })

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self):  # noqa: N802
        self._dispatch("PATCH")

    def do_DELETE(self):  # noqa: N802
        self._dispatch("DELETE")


class SettingsServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, app: SettingsApp, token: str, port: int = 0):
        super().__init__(("127.0.0.1", port), _Handler)
        self.app = app
        self.token = token
        self.lock = threading.Lock()  # one SQLite writer at a time

    @property
    def port(self) -> int:
        return self.server_address[1]
