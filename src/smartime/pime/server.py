"""PIME backend server loop.

Protocol (one message per line, UTF-8):
    request : ``<client_id>|<json>``
    response: ``PIME_MSG|<client_id>|<json>``

stdout is reserved for protocol replies; diagnostics go to a log file in the
user data folder (stderr is captured by PIMELauncher's own log as errors).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import time
from pathlib import Path

from .. import paths
from ..config import Config
from ..engine.decoder import Decoder
from ..engine.layouts import get_layout
from ..engine.lexicon import Lexicon
from ..engine.userdict import UserDict
from ..engine.session import Engine
from .text_service import SmartTextService

log = logging.getLogger("smartime.pime")


def setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(
        paths.log_dir() / "backend.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def build_engine() -> Engine:
    config = Config.load(paths.config_path())
    try:
        user = UserDict(paths.user_db_path())
        user.tidy()  # forget old one-off picks (cheap; no VACUUM here)
    except Exception:
        # A broken user.db must never stop typing; run without memory.
        log.exception("cannot open the user dictionary; continuing without it")
        user = None
    lexicon = Lexicon(paths.system_db_path(), user)
    layout = get_layout(config.layout)
    decoder = Decoder(lexicon, layout)
    decoder.apply_config(config)
    from ..engine.symbols import SymbolPanel

    engine = Engine(lexicon=lexicon, layout=layout, decoder=decoder, config=config,
                    config_path=paths.config_path(),
                    symbols=SymbolPanel(paths.user_dir() / "recent-symbols.json"))
    engine.refresh()  # record the config file's current mtime
    return engine


def serve(stdin, stdout, engine: Engine, icon_dir: Path) -> None:
    clients: dict[str, SmartTextService] = {}
    for raw in stdin:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        client_id = ""
        seq = 0
        try:
            client_id, payload = line.split("|", 1)
            msg = json.loads(payload)
            seq = msg.get("seqNum", 0)
            if msg.get("method") == "close":
                clients.pop(client_id, None)
                SmartTextService.icons_invalidated()  # PIME clears the app's icon cache here too
                log.info("client closed: %s", client_id)
                continue
            service = clients.get(client_id)
            if service is None:
                service = clients[client_id] = SmartTextService(engine, icon_dir)
                log.info("client connected: %s", client_id)
            t0 = time.perf_counter()
            reply = service.handle(msg)
            elapsed = (time.perf_counter() - t0) * 1000
            if elapsed > 30:
                log.warning("slow %s: %.1f ms", msg.get("method"), elapsed)
        except Exception:
            log.exception("error handling: %s", line[:500])
            reply = {"success": False, "seqNum": seq}
        out = "|".join(("PIME_MSG", client_id, json.dumps(reply, ensure_ascii=False))) + "\n"
        stdout.write(out.encode("utf-8"))
        stdout.flush()


def main(icon_dir: Path) -> None:
    setup_logging()
    log.info("backend starting (python %s)", sys.version.split()[0])
    try:
        engine = build_engine()
    except Exception:
        log.exception("failed to load engine")
        raise
    log.info("lexicon %s", engine.lexicon.meta)
    serve(sys.stdin.buffer, sys.stdout.buffer, engine, icon_dir)
    log.info("stdin closed; backend exiting")
