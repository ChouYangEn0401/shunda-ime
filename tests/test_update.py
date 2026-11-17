"""The update check: when it runs, what it picks, and the tray icon's dot.

Nothing here goes online: GitHub's answers are canned."""

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

import smartime
from smartime import update as upd
from smartime.config import Config
from smartime.pime.text_service import ID_UPDATE, SmartTextService


def ts(*args) -> float:
    return datetime(*args).timestamp()


# 2026-11-20 is a Friday (weekday 4)
FRI_1400 = ts(2026, 11, 20, 14, 0)


def test_default_schedule_is_friday_afternoon():
    cfg = Config()
    assert cfg.update_check is True
    assert (cfg.update_weekday, cfg.update_hour) == (4, 14)


def test_last_and_next_slot_weekly():
    assert upd.last_slot(ts(2026, 11, 20, 14, 0)) == FRI_1400  # exactly at the slot
    assert upd.last_slot(ts(2026, 11, 20, 13, 59)) == ts(2026, 11, 13, 14, 0)  # just before: last week's
    assert upd.last_slot(ts(2026, 11, 24, 9, 0)) == FRI_1400  # the Tuesday after
    assert upd.next_slot(ts(2026, 11, 18, 10, 0)) == FRI_1400  # Wednesday -> this Friday
    assert upd.next_slot(FRI_1400) == ts(2026, 11, 27, 14, 0)  # at the slot -> next week's


def test_last_slot_daily():
    assert upd.last_slot(ts(2026, 11, 18, 15, 0), weekday=-1, hour=9) == ts(2026, 11, 18, 9, 0)
    assert upd.last_slot(ts(2026, 11, 18, 8, 0), weekday=-1, hour=9) == ts(2026, 11, 17, 9, 0)
    assert upd.next_slot(ts(2026, 11, 18, 8, 0), weekday=-1, hour=9) == ts(2026, 11, 18, 9, 0)


def test_due_once_per_slot_and_catches_up_after_the_computer_was_off():
    never = upd.Release()
    assert upd.due(ts(2026, 11, 18, 10, 0), never)  # first run: check once
    checked_wed = upd.Release(version="1.0.0", checked=ts(2026, 11, 18, 10, 0))
    assert not upd.due(ts(2026, 11, 20, 13, 0), checked_wed)  # Friday morning: not yet
    assert upd.due(ts(2026, 11, 20, 14, 5), checked_wed)  # Friday afternoon: yes
    # the computer was off on Friday: the first use afterwards checks
    assert upd.due(ts(2026, 11, 23, 8, 0), checked_wed)
    checked_fri = upd.Release(version="1.0.0", checked=ts(2026, 11, 20, 14, 5))
    assert not upd.due(ts(2026, 11, 26, 20, 0), checked_fri)


def test_a_failed_check_is_retried_an_hour_later_not_a_week_later():
    failed = upd.Release(checked=ts(2026, 11, 20, 14, 5), error="offline")
    assert not upd.due(ts(2026, 11, 20, 14, 30), failed)
    assert upd.due(ts(2026, 11, 20, 15, 10), failed)


def test_config_keeps_the_schedule_in_range():
    cfg = Config.from_dict({"update_weekday": 9, "update_hour": 30})
    assert (cfg.update_weekday, cfg.update_hour) == (4, 23)
    assert Config.from_dict({"update_weekday": -1}).update_weekday == -1


def test_test_builds_hear_about_test_builds():
    assert upd.wants_prereleases("0.10.0-alpha.1")
    assert upd.wants_prereleases("0.9.0-rc.1")
    assert not upd.wants_prereleases("0.10.0")


def test_pick_release_takes_the_highest_version_not_the_newest_date():
    listing = [
        {"tag_name": "v0.9.1", "draft": False},  # a later patch of the old line
        {"tag_name": "v0.10.0-alpha.2", "draft": False, "prerelease": True},
        {"tag_name": "v0.11.0", "draft": True},  # drafts are not out yet
        {"tag_name": "v0.9.0-rc.1", "draft": False},
    ]
    assert upd.pick_release(listing)["tag_name"] == "v0.10.0-alpha.2"
    assert upd.pick_release([]) is None


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _github(monkeypatch, listing, latest):
    seen = []

    def urlopen(req, timeout=0):
        seen.append(req.full_url)
        return FakeResponse(listing if req.full_url == upd.API_LIST else latest)

    monkeypatch.setattr(upd.urllib.request, "urlopen", urlopen)
    return seen


ASSET = {"name": "ShundaIME-Setup-0.10.0-alpha.2.exe", "browser_download_url": "https://x/setup.exe", "size": 123}


def test_check_on_a_test_build_reads_the_whole_list(monkeypatch):
    monkeypatch.setattr(upd, "__version__", "0.10.0-alpha.1")
    listing = [{"tag_name": "v0.10.0-alpha.2", "assets": [ASSET], "html_url": "https://x/r"},
               {"tag_name": "v0.9.0-rc.1", "assets": []}]
    seen = _github(monkeypatch, listing, {"tag_name": "v0.9.0-rc.1"})
    r = upd.check()
    assert seen == [upd.API_LIST]
    assert r.version == "0.10.0-alpha.2" and r.asset_url == "https://x/setup.exe" and r.newer
    assert upd.cached().version == "0.10.0-alpha.2"


def test_check_on_a_release_reads_only_latest(monkeypatch):
    monkeypatch.setattr(upd, "__version__", "0.10.0")
    seen = _github(monkeypatch, [], {"tag_name": "v0.10.1", "assets": []})
    assert upd.check().version == "0.10.1"
    assert seen == [upd.API]


def test_scheduled_check_runs_only_when_due_and_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(upd, "check", lambda force=True: calls.append(1) or upd.Release(checked=time.time()))
    assert not upd.run_schedule_once(Config(update_check=False))
    assert upd.run_schedule_once(Config())  # never checked: due
    assert calls == [1]


def _write_cache(version):
    upd.cache_path().parent.mkdir(parents=True, exist_ok=True)
    upd._store(upd.Release(version=version, checked=time.time()))
    upd._seen["looked"] = 0.0


def test_available_follows_the_cache():
    assert upd.available() == ""
    _write_cache("99.0.0")
    assert upd.available() == "99.0.0"
    _write_cache(smartime.__version__)
    assert upd.available() == ""


def test_tray_icon_gets_a_red_dot_and_the_menu_leads_with_the_update(engine):
    svc = SmartTextService(engine, Path("icons"))
    reply = svc.handle({"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True})
    assert reply["addButton"][0]["icon"].endswith("auto.ico")
    assert svc.handle({"method": "onMenu", "seqNum": 2})["return"][0]["id"] != ID_UPDATE

    _write_cache("99.0.0")
    reply = svc.handle({"method": "onKeyUp", "seqNum": 3, "keyCode": 0x10, "charCode": 0, "keyStates": [0] * 256})
    button = reply["changeButton"][0]
    assert button["icon"].endswith("auto-new.ico") and "99.0.0" in button["tooltip"]
    menu = svc.handle({"method": "onMenu", "seqNum": 4})["return"]
    assert menu[0]["id"] == ID_UPDATE and "99.0.0" in menu[0]["text"] and menu[1] == {}

    # the user turned the check off: no dot, no nagging
    engine.config.update_check = False
    reply = svc.handle({"method": "onKeyUp", "seqNum": 5, "keyCode": 0x10, "charCode": 0, "keyStates": [0] * 256})
    assert reply["changeButton"][0]["icon"].endswith("auto.ico")


def test_every_mode_icon_has_a_dotted_twin():
    from smartime.pime.text_service import MODE_ICONS

    icons = Path(smartime.__file__).resolve().parents[2] / "backend" / "input_methods" / "smartime" / "icons"
    for name in MODE_ICONS.values():
        assert (icons / name.replace(".ico", "-new.ico")).stat().st_size > 1000


@pytest.mark.parametrize("weekday", [-1, 0, 4, 6])
def test_next_slot_is_always_in_the_future(weekday):
    now = time.time()
    assert now < upd.next_slot(now, weekday, 14) <= now + 7 * 86400 + 3600


def test_a_hotfix_of_a_test_build_sorts_between():
    v = upd.version_tuple
    assert v("0.10.0-alpha.1") < v("0.10.0-alpha.1.1") < v("0.10.0-alpha.2") < v("0.10.0")


def test_the_schedule_takes_any_minute():
    """Reported: the hour was a list of five (「你時間幹嘛寫死」), so a check
    could not be set a minute ahead to watch it happen."""
    assert upd.last_slot(ts(2026, 11, 20, 15, 31), 4, 15, 30) == ts(2026, 11, 20, 15, 30)
    assert upd.last_slot(ts(2026, 11, 20, 15, 29), 4, 15, 30) == ts(2026, 11, 13, 15, 30)
    assert upd.next_slot(ts(2026, 11, 18, 9, 0), -1, 9, 5) == ts(2026, 11, 18, 9, 5)
    checked = upd.Release(version="1", checked=ts(2026, 11, 20, 15, 0))
    assert not upd.due(ts(2026, 11, 20, 15, 29), checked, 4, 15, 30)
    assert upd.due(ts(2026, 11, 20, 15, 30), checked, 4, 15, 30)
    assert Config.from_dict({"update_minute": 75}).update_minute == 59
    assert upd.POLL <= 60  # a time set a minute ahead happens about then


def test_auto_install_opens_the_installer_once_per_version(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(upd, "download", lambda r, progress=None: tmp_path / "setup.exe")
    monkeypatch.setattr(upd, "run_installer", lambda p: opened.append(p))
    r = upd.Release(version="99.0.0", asset_url="https://x/setup.exe", checked=time.time())
    assert upd.auto_install(r) and len(opened) == 1
    assert upd.cached().started == "99.0.0"
    assert not upd.auto_install(upd.cached())  # cancelled UAC: not again every minute
    assert not upd.auto_install(upd.Release(version="99.0.1"))  # no installer attached
    assert len(opened) == 1


def test_scheduled_check_auto_installs_only_when_asked(monkeypatch):
    calls = []
    monkeypatch.setattr(upd, "check", lambda force=True: upd.Release(version="99.0.0", asset_url="u",
                                                                    checked=time.time()))
    monkeypatch.setattr(upd, "auto_install", lambda r: calls.append(r.version))
    upd.run_schedule_once(Config())
    assert calls == []
    upd._store(upd.Release())  # due again
    upd.run_schedule_once(Config(update_auto_install=True))
    assert calls == ["99.0.0"]


def test_a_release_without_an_installer_is_said(monkeypatch):
    """Reported: 「有新版本 0.10.0-alpha.2」 and no button — the GitHub release
    had no .exe attached. The page needs to know to say so."""
    from smartime.settings.api import SettingsApp

    app = SettingsApp()
    monkeypatch.setattr(upd, "cached", lambda: upd.Release(version="99.0.0", url="https://x/r"))
    state = app.update_state()
    assert state["newer"] and not state["canInstall"] and state["url"] == "https://x/r"
    app.close()
