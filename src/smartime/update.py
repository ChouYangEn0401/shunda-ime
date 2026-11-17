"""Is there a newer 順打輸入法? Ask GitHub, and nothing else.

Competitors do this with a background service: 華碩智慧輸入法 ships its own
updater and a 最新消息 page, Microsoft's IMEs ride on Windows Update. Neither
is open to a PIME backend, and neither is something this project wants —
the whole point of the product is that it works offline and sends nothing.

So the check is the smallest thing that can work:

* one HTTPS GET to the public GitHub Releases API, no account, no token,
  no identifier beyond the User-Agent below (which names the product and
  version so a maintainer can see what is in the field);
* on a schedule the user picks (default: once a week, Friday afternoon —
  ``due``), and only when ``Config.update_check`` says so. The backend runs
  the schedule in a background thread (``start_background``); a check that
  failed (offline) is retried an hour later, not a week later;
* against ``releases/latest``, which GitHub defines as the newest release
  *not* marked as a pre-release — so an alpha build never offers itself to
  somebody running a release, and somebody running one is still told when
  the real release lands (see ``version_tuple``). Somebody already running
  a test build (``0.10.0-alpha.1``) asked for test builds, so they are told
  about newer ones too (``wants_prereleases``);
* when there is something newer, the tray icon gets a red dot
  (``available``) and its menu's first entry says so;
* it never installs anything by itself. It reports, the user decides
  (``download`` fetches the installer and ``run_installer`` starts it, with
  the usual elevation prompt).

The result is cached in ``%APPDATA%\\SmartIME\\update.json`` so the settings
page can show it without going online again.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import PRODUCT_NAME, __version__
from .paths import user_dir

log = logging.getLogger(__name__)

REPO = "ChouYangEn0401/shunda-ime"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
API_LIST = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
USER_AGENT = f"ShundaIME/{__version__} (+https://github.com/{REPO})"
TIMEOUT = 8.0
EVERY = 24 * 3600  # check(force=False): how long a cached answer counts as fresh
RETRY = 3600  # a scheduled check that failed (offline) is tried again after this
CACHE_NAME = "update.json"
# Default schedule (Config.update_weekday / update_hour): Friday, 14:00 local.
DEFAULT_WEEKDAY = 4  # Monday = 0 … Sunday = 6; -1 = every day
DEFAULT_HOUR = 14
POLL = 600  # seconds between the background thread's looks at the schedule
FIRST_LOOK = 90  # …and the first one, so starting to type never waits on it


@dataclass
class Release:
    version: str = ""  # "0.7.0" (the tag without its leading v)
    url: str = RELEASES_PAGE  # the release page for a human
    asset_url: str = ""  # the setup .exe
    asset_name: str = ""
    size: int = 0
    notes: str = ""
    published: str = ""
    checked: float = 0.0  # when we last asked (epoch seconds)
    error: str = ""  # why the last check failed, for the settings page

    @property
    def newer(self) -> bool:
        return bool(self.version) and version_tuple(self.version) > version_tuple(__version__)


PRE_RANK = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2}


def version_tuple(v: str) -> tuple:
    """Sortable form of a version, pre-releases included.

    ``0.8.0-alpha.3`` < ``0.8.0-rc.1`` < ``0.8.0``, so somebody running a
    test build is told about the real release when it lands. Anything
    unparsable sorts first rather than claiming to be newer.
    """
    base, _, pre = v.strip().lstrip("vV").partition("-")
    nums = []
    for part in base.split("."):
        digits = "".join(c for c in part if c.isdigit())
        nums.append(int(digits) if digits else 0)
    nums = (nums + [0, 0, 0])[:3]
    if not pre:
        return (*nums, 9, 0)  # a release is newer than every pre-release of it
    kind, _, n = pre.partition(".")
    digits = "".join(c for c in n if c.isdigit())
    return (*nums, PRE_RANK.get(kind.rstrip("0123456789").lower(), 0), int(digits) if digits else 0)


def cache_path() -> Path:
    return user_dir() / CACHE_NAME


def cached() -> Release:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
        return Release(**{k: v for k, v in data.items() if k in Release.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return Release()


def _store(release: Release) -> Release:
    try:
        cache_path().write_text(json.dumps(asdict(release), ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        log.debug("cannot write the update cache", exc_info=True)
    return release


def wants_prereleases(version: str | None = None) -> bool:
    """A test build (``0.10.0-alpha.1``) is told about newer test builds;
    a release only about newer releases."""
    return "-" in (__version__ if version is None else version).strip()


def pick_release(releases: list) -> dict | None:
    """The newest entry of GitHub's release list (drafts skipped), by
    version rather than by date: a 0.9.1 patch published after 0.10.0 must
    not be offered to somebody on 0.10.0."""
    best = None
    for data in releases:
        if not isinstance(data, dict) or data.get("draft"):
            continue
        if best is None or version_tuple(str(data.get("tag_name", ""))) > version_tuple(str(best.get("tag_name", ""))):
            best = data
    return best


def last_slot(now: float, weekday: int = DEFAULT_WEEKDAY, hour: int = DEFAULT_HOUR) -> float:
    """The latest scheduled moment at or before ``now`` (local time):
    ``weekday`` at ``hour``:00, or every day at ``hour`` when weekday is -1."""
    d = datetime.fromtimestamp(now)
    slot = d.replace(hour=max(0, min(23, hour)), minute=0, second=0, microsecond=0)
    if weekday >= 0:
        slot -= timedelta(days=(slot.weekday() - weekday) % 7)
    if slot > d:
        slot -= timedelta(days=7 if weekday >= 0 else 1)
    return slot.timestamp()


def next_slot(now: float, weekday: int = DEFAULT_WEEKDAY, hour: int = DEFAULT_HOUR) -> float:
    """The first scheduled moment after ``now``."""
    return last_slot(now + (7 if weekday >= 0 else 1) * 86400, weekday, hour)


def due(now: float, release: Release, weekday: int = DEFAULT_WEEKDAY, hour: int = DEFAULT_HOUR) -> bool:
    """Should the scheduled check run now? Yes when the last check is older
    than the latest scheduled moment — so a computer that was off on Friday
    afternoon checks the next time it is used — or when the last check
    failed and an hour has passed."""
    if release.error and now - release.checked >= RETRY:
        return True
    return release.checked < last_slot(now, weekday, hour)


def _get_json(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed https URL
        return json.loads(r.read().decode("utf-8"))


def check(force: bool = True) -> Release:
    """Ask GitHub for the latest release. ``force=False`` answers from the
    cache while it is fresh, so starting the backend never waits on a
    network round trip."""
    old = cached()
    if not force and old.checked and time.time() - old.checked < EVERY:
        return old
    release = Release(checked=time.time())
    try:
        if wants_prereleases():
            data = pick_release(_get_json(API_LIST)) or {}
        else:
            data = _get_json(API)
        if not isinstance(data, dict):
            raise ValueError("unexpected answer from GitHub")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        # offline is the normal case for this product, not a failure
        release.error = str(e)
        release.version, release.url = old.version, old.url
        release.notes, release.published = old.notes, old.published
        release.asset_url, release.asset_name = old.asset_url, old.asset_name
        return _store(release)
    release.version = str(data.get("tag_name", "")).lstrip("vV")
    release.url = str(data.get("html_url") or RELEASES_PAGE)
    release.notes = str(data.get("body") or "")[:4000]
    release.published = str(data.get("published_at") or "")
    for asset in data.get("assets") or []:
        name = str(asset.get("name", ""))
        if name.lower().endswith(".exe"):
            release.asset_url = str(asset.get("browser_download_url", ""))
            release.asset_name = name
            release.size = int(asset.get("size") or 0)
            break
    return _store(release)


def download(release: Release, progress=None) -> Path:
    """Fetch the installer into %TEMP% and return where it landed."""
    if not release.asset_url:
        raise ValueError("this release has no installer to download")
    target = Path(os.environ.get("TEMP", ".")) / (release.asset_name or f"{PRODUCT_NAME}-setup.exe")
    req = urllib.request.Request(release.asset_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT * 4) as r:  # noqa: S310 - github release asset
        total = int(r.headers.get("Content-Length") or release.size or 0)
        done = 0
        with open(target, "wb") as f:
            while chunk := r.read(256 * 1024):
                f.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    return target


def run_installer(path: Path) -> None:
    """Start the downloaded installer. It asks for administrator rights
    itself; we never install anything without the user seeing that."""
    os.startfile(str(path))  # noqa: S606 - a file this module just downloaded


# ------------------------------------------------------------ background
# The backend (the process that draws the tray icon) runs the schedule. The
# settings page may also check, in its own process; both write update.json,
# so ``available`` reads that file (at most every few seconds) rather than
# keeping its own answer.
_seen = {"mtime": -1.0, "looked": 0.0, "version": ""}
LOOK_EVERY = 5.0  # seconds; ``available`` is called on every key


def available(now: float | None = None) -> str:
    """The newer version waiting to be installed, or "" — what puts the dot
    on the tray icon. Cheap: one stat() every few seconds."""
    now = time.time() if now is None else now
    if now - _seen["looked"] < LOOK_EVERY:
        return _seen["version"]
    _seen["looked"] = now
    try:
        mtime = cache_path().stat().st_mtime
    except OSError:
        mtime = 0.0
    if mtime != _seen["mtime"]:
        _seen["mtime"] = mtime
        release = cached()
        _seen["version"] = release.version if release.newer else ""
    return _seen["version"]


def run_schedule_once(config, now: float | None = None) -> bool:
    """One look at the schedule; True when a check was made."""
    if not getattr(config, "update_check", False):
        return False
    now = time.time() if now is None else now
    if not due(now, cached(), getattr(config, "update_weekday", DEFAULT_WEEKDAY),
               getattr(config, "update_hour", DEFAULT_HOUR)):
        return False
    release = check(force=True)
    log.info("scheduled update check: latest %s%s", release.version or "?",
             f" (error: {release.error})" if release.error else "")
    _seen["looked"] = 0.0  # let the tray icon see the answer at once
    return True


_thread: threading.Thread | None = None


def start_background(get_config) -> None:
    """Run the schedule in a daemon thread for as long as the backend lives.
    ``get_config`` returns the current Config (it changes when the settings
    page saves)."""
    global _thread
    if _thread is not None or os.environ.get("SMARTIME_NO_UPDATE_THREAD"):
        return

    def loop() -> None:
        time.sleep(FIRST_LOOK)
        while True:
            try:
                run_schedule_once(get_config())
            except Exception:  # noqa: BLE001 - never take the backend down
                log.exception("scheduled update check failed")
            time.sleep(POLL)

    _thread = threading.Thread(target=loop, name="update-schedule", daemon=True)
    _thread.start()
