"""Is there a newer 順打輸入法? Ask GitHub, and nothing else.

Competitors do this with a background service: 華碩智慧輸入法 ships its own
updater and a 最新消息 page, Microsoft's IMEs ride on Windows Update. Neither
is open to a PIME backend, and neither is something this project wants —
the whole point of the product is that it works offline and sends nothing.

So the check is the smallest thing that can work:

* one HTTPS GET to the public GitHub Releases API, no account, no token,
  no identifier beyond the User-Agent below (which names the product and
  version so a maintainer can see what is in the field);
* at most once a day, and only when ``Config.update_check`` says so;
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
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import PRODUCT_NAME, __version__
from .paths import user_dir

log = logging.getLogger(__name__)

REPO = "ChouYangEn0401/shunda-ime"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
USER_AGENT = f"ShundaIME/{__version__} (+https://github.com/{REPO})"
TIMEOUT = 8.0
EVERY = 24 * 3600  # seconds between automatic checks
CACHE_NAME = "update.json"


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


def version_tuple(v: str) -> tuple:
    """"0.10.2" -> (0, 10, 2). Anything unparsable sorts first."""
    out = []
    for part in v.strip().lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out + [0] * (3 - len(out)))[:3]


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


def check(force: bool = True) -> Release:
    """Ask GitHub for the latest release. ``force=False`` answers from the
    cache while it is fresh, so starting the backend never waits on a
    network round trip."""
    old = cached()
    if not force and old.checked and time.time() - old.checked < EVERY:
        return old
    release = Release(checked=time.time())
    try:
        req = urllib.request.Request(API, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed https URL
            data = json.loads(r.read().decode("utf-8"))
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
