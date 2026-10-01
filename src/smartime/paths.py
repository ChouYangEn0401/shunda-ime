"""Filesystem locations, resolved at runtime so nothing machine-specific is
hard-coded (the same build must work on any PC and for any Windows user).

* System data (read-only lexicon): next to the package — ``<root>/data/generated``
  where ``<root>`` is the repo in development or ``<backend>/app`` when deployed.
* User data (config, learned words, logs): ``%APPDATA%\\SmartIME`` by default,
  overridable with ``SMARTIME_USER_DIR``. Keeping it per-user and in one folder
  makes "export my memory to another PC" a simple copy/zip.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "SmartIME"


def app_root() -> Path:
    # src/smartime/paths.py -> parents[2] is the repo / deployed app root
    return Path(__file__).resolve().parents[2]


def system_db_path() -> Path:
    env = os.environ.get("SMARTIME_SYSTEM_DB")
    if env:
        return Path(env)
    return app_root() / "data" / "generated" / "smartime.db"


def user_dir() -> Path:
    env = os.environ.get("SMARTIME_USER_DIR")
    if env:
        base = Path(env)
    else:
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata) / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return user_dir() / "config.json"


def log_dir() -> Path:
    d = user_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
