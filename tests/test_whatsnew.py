"""這一版的新功能: the red dots for new features (whatsnew.py)."""

from pathlib import Path

from smartime import paths, whatsnew
from smartime.pime.text_service import ID_UPDATE, ID_WHATSNEW, SmartTextService


def fresh_counts():
    whatsnew._cache.update(mtime=-1.0, looked=0.0, count=0)


def test_a_fresh_install_starts_with_nothing_new():
    """A newcomer gets the 練習場 tour, not a page of red dots."""
    whatsnew.ensure_baseline()
    assert whatsnew.unseen() == []


def test_an_upgrade_starts_with_everything_new():
    paths.user_dir().mkdir(parents=True, exist_ok=True)
    paths.config_path().write_text("{}", encoding="utf-8")  # an older version was here
    whatsnew.ensure_baseline()
    assert [f.id for f in whatsnew.unseen()] == list(whatsnew.IDS)
    whatsnew.ensure_baseline()  # only once: never resets what was seen
    assert whatsnew.mark_seen(["update-check", "no-such-id"]) == 1
    assert "update-check" not in {f.id for f in whatsnew.unseen()}
    assert whatsnew.mark_seen() == len(whatsnew.IDS) - 1
    assert whatsnew.unseen() == []


def test_every_feature_points_at_a_page_and_a_row():
    """data-new="<id>" must be on the settings page, or the tag has nowhere to go."""
    html = (Path(__file__).resolve().parents[1] / "src/smartime/settings/ui/index.html").read_text(encoding="utf-8")
    for f in whatsnew.FEATURES:
        assert f'data-view="{f.view}"' in html, f.view
        assert f'data-new="{f.id}"' in html, f.id
    assert len(set(whatsnew.IDS)) == len(whatsnew.IDS)


def test_tray_icon_dot_and_menu_for_new_features(engine):
    paths.user_dir().mkdir(parents=True, exist_ok=True)
    paths.config_path().write_text("{}", encoding="utf-8")
    whatsnew.ensure_baseline()
    fresh_counts()
    svc = SmartTextService(engine, Path("icons"))
    reply = svc.handle({"method": "onActivate", "seqNum": 1, "isKeyboardOpen": True})
    button = reply["addButton"][0]
    assert button["icon"].endswith("auto-new.ico") and "新功能" in button["tooltip"]
    menu = svc.handle({"method": "onMenu", "seqNum": 2})["return"]
    assert menu[0]["id"] == ID_WHATSNEW and f"{len(whatsnew.IDS)} 項新功能" in menu[0]["text"]
    assert ID_UPDATE not in [m.get("id") for m in menu[:2]]

    whatsnew.mark_seen()
    fresh_counts()
    reply = svc.handle({"method": "onKeyUp", "seqNum": 3, "keyCode": 0x10, "charCode": 0, "keyStates": [0] * 256})
    assert reply["changeButton"][0]["icon"].endswith("auto.ico")
    assert svc.handle({"method": "onMenu", "seqNum": 4})["return"][0]["id"] != ID_WHATSNEW


def test_settings_api_lists_and_marks(tmp_path):
    from smartime.settings.api import SettingsApp

    paths.user_dir().mkdir(parents=True, exist_ok=True)
    paths.config_path().write_text("{}", encoding="utf-8")
    app = SettingsApp()
    rows = app.whatsnew()["features"]
    assert rows and not any(r["seen"] for r in rows) and {"view", "title", "text", "version"} <= set(rows[0])
    after = app.whatsnew_seen({"ids": [rows[0]["id"]]})
    assert after["marked"] == 1 and after["features"][0]["seen"]
    assert app.whatsnew_seen({"all": True})["marked"] == len(rows) - 1
    app.close()


def test_tray_menu_command_ids_are_unique():
    """ID_WHATSNEW first took 10, which is 中英自動's entry: picking 「新功能」
    would have switched the mode instead."""
    from smartime.pime import text_service as ts

    ids = [ts.ID_MODE_ICON, ts.ID_PRACTICE, ts.ID_ABOUT, ts.ID_SETTINGS, ts.ID_SETTINGS_PUNCT, ts.ID_SETTINGS_DICT,
           ts.ID_SETTINGS_KEYS, ts.ID_UPDATE, ts.ID_RESTART, ts.ID_WHATSNEW,
           *ts.MODE_MENU_IDS, *ts.TOGGLES, *ts.CHOICES]
    assert len(ids) == len(set(ids))
