"""Change the version number everywhere it is written, in one command.

    .venv\\Scripts\\python tools\\set_version.py          # show the current version (and check all copies agree)
    .venv\\Scripts\\python tools\\set_version.py 0.4.0    # set a new version

The source of truth is ``src/smartime/__init__.py`` (``__version__``); the
installer, the settings page and the export file read it from there. Copies
that must hold a literal value are updated by this script:

* ``pyproject.toml``                              (package metadata)
* ``backend/input_methods/smartime/ime.json``     (PIME reads it; no BOM allowed)

``tests/test_backend_files.py`` fails if they ever disagree. CHANGELOG.md is
written by hand: the script reminds you when it has no section for the version.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# SemVer, with an optional pre-release: 0.8.0, 0.8.0-alpha.3, 0.8.0-rc.1.
# Test builds on the way to a release are tagged like that, and the real
# release is the plain number — see CONTRIBUTING.md §6.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$")
PEP440 = {"alpha": "a", "beta": "b", "rc": "rc"}


def pep440(version: str) -> str:
    """pyproject.toml must hold a version Python's tools accept, and they
    spell 0.8.0-alpha.3 as 0.8.0a3."""
    base, _, pre = version.partition("-")
    if not pre:
        return base
    kind, _, n = pre.partition(".")
    return f"{base}{PEP440[kind]}{n}"

# (file, pattern with one group around the version, how to write it back)
COPIES = [
    ("src/smartime/__init__.py", r'^__version__ = "([^"]+)"', '__version__ = "{v}"'),
    ("pyproject.toml", r'^version = "([^"]+)"', 'version = "{v}"'),
    ("backend/input_methods/smartime/ime.json", r'^    "version": "([^"]+)",', '    "version": "{v}",'),
]


def agree(versions: dict[str, str | None]) -> bool:
    """All copies hold the same version — pyproject in its own spelling."""
    main = versions.get("src/smartime/__init__.py")
    if main is None:
        return False
    return all(v == (pep440(main) if rel == "pyproject.toml" else main) for rel, v in versions.items())


def read(rel: str) -> bytes:
    return (ROOT / rel).read_bytes()


def current() -> dict[str, str | None]:
    out = {}
    for rel, pattern, _ in COPIES:
        text = read(rel).decode("utf-8")
        m = re.search(pattern, text, re.M)
        out[rel] = m.group(1) if m else None
    return out


def set_version(new: str) -> None:
    for rel, pattern, template in COPIES:
        value = pep440(new) if rel == "pyproject.toml" else new
        raw = read(rel)
        newline = "\r\n" if b"\r\n" in raw else "\n"
        text = raw.decode("utf-8").replace("\r\n", "\n")
        text, n = re.subn(pattern, template.format(v=value), text, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"找不到 {rel} 裡的版本號")
        (ROOT / rel).write_bytes(text.replace("\n", newline).encode("utf-8"))  # never adds a BOM


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    versions = current()
    if len(sys.argv) < 2:
        for rel, v in versions.items():
            print(f"{v or '（找不到）':16} {rel}")
        if not agree(versions):
            print("版本號不一致：用 tools/set_version.py <版本> 統一")
            return 1
        return 0
    new = sys.argv[1].lstrip("v")
    if not VERSION_RE.match(new):
        print(f"版本號格式不對：{new}（例：0.8.0，或測試版 0.8.0-alpha.3 / 0.8.0-rc.1）")
        return 2
    set_version(new)
    print(f"版本改成 {new}：" + "、".join(rel for rel, _, _ in COPIES))
    if f"## {new}" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"):
        print(f"提醒：CHANGELOG.md 還沒有「## {new}」這一節")
    return 0


if __name__ == "__main__":
    sys.exit(main())
