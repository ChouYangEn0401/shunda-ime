"""Static checks for files PIME reads directly (jsoncpp is unforgiving)."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "backend" / "input_methods" / "smartime" / "ime.json"
GUID = "{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}"


def test_ime_manifest_is_valid_json_without_bom():
    raw = MANIFEST.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "jsoncpp in PIME does not accept a BOM"
    data = json.loads(raw.decode("utf-8"))
    assert data["guid"] == GUID
    assert data["locale"] == "zh-Hant-TW"
    assert (MANIFEST.parent / data["icon"].replace("\\", "/")).is_file()


def test_guid_is_consistent_across_scripts():
    for path in [ROOT / "scripts" / n for n in ("install.ps1", "install-admin.ps1", "uninstall.ps1",
                                                  "uninstall-admin.ps1", "tsf-profile.ps1")]:
        text = path.read_text(encoding="ascii")
        guids = set(re.findall(r"\{61AA71DB-[0-9A-F-]+\}", text, re.I))
        assert guids <= {GUID}, f"{path.name}: {guids}"


def test_icons_exist():
    for name in ("ime.ico", "auto.ico", "chinese.ico", "english.ico"):
        assert (MANIFEST.parent / "icons" / name).stat().st_size > 1000
