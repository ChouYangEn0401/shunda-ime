"""Static checks for the installer: the helper scripts it runs, the files
PIME parses, and the PIME core taken out of the official setup."""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "smartime.iss"
BUILD = ROOT / "tools" / "build_installer.py"


def load_build_installer():
    spec = importlib.util.spec_from_file_location("build_installer", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_backends(action: str, pime: Path) -> list[dict]:
    script = ROOT / "scripts" / "pime_backends.py"
    subprocess.run([sys.executable, str(script), action, str(pime)], check=True, capture_output=True)
    raw = (pime / "backends.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # jsoncpp in PIME cannot read a BOM
    return json.loads(raw.decode("utf-8"))


def test_backends_only_lists_just_us(tmp_path):
    (tmp_path / "backends.json").write_text('[{"name": "python"}]', encoding="utf-8")
    assert [b["name"] for b in run_backends("only", tmp_path)] == ["smartime"]


def test_backends_add_keeps_other_backends_and_creates_a_missing_file(tmp_path):
    assert [b["name"] for b in run_backends("add", tmp_path)] == ["smartime"]
    (tmp_path / "backends.json").write_text('[{"name": "python"}, {"name": "node"}]', encoding="utf-8")
    assert [b["name"] for b in run_backends("add", tmp_path)] == ["python", "node", "smartime"]
    assert [b["name"] for b in run_backends("remove", tmp_path)] == ["python", "node"]


def test_every_helper_the_installer_runs_is_staged():
    iss = ISS.read_text(encoding="utf-8")
    used = set(re.findall(r"\\installer\\([\w.-]+\.(?:ps1|py))", iss))
    assert used, "no helper references found"
    build = BUILD.read_text(encoding="utf-8")
    staged = set(re.findall(r'ROOT / "(?:scripts|installer)" / "([\w.-]+)"', build))
    assert used <= staged, f"not staged: {used - staged}"


def test_iss_gets_every_define_it_uses():
    iss = ISS.read_text(encoding="utf-8")
    used = set(re.findall(r"\{#(\w+)\}", iss))
    build = BUILD.read_text(encoding="utf-8")
    defined = set(re.findall(r"#define (\w+) ", build))
    assert used <= defined, f"not defined by build_installer.py: {used - defined}"


def test_pime_core_is_in_the_official_setup():
    bi = load_build_installer()
    setup = bi.CACHE / "PIME-1.3.0-stable-setup.exe"
    if not setup.exists():
        pytest.skip("PIME setup not downloaded yet (tools/build_installer.py fetches it)")
    files = bi.nsis_files(setup)
    for rel, digest in bi.PIME_CORE.items():
        blob = files.get(digest)
        assert blob is not None, rel
        assert blob[:2] == b"MZ", rel
        machine = int.from_bytes(blob[int.from_bytes(blob[0x3C:0x40], "little") + 4:][:2], "little")
        assert machine == (0x8664 if rel.startswith("x64") else 0x14C), rel
