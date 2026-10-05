"""Build the Windows installer: dist/ShundaIME-Setup-<version>.exe

Steps
  1. Stage the files that go to <PIME>\\smartime: backend entry point, IME
     manifest + icons, the engine sources, the system lexicon, a private
     embeddable Python, installer helper scripts and license notices.
  2. Stage the PIME core (PIMELauncher.exe and the 32/64-bit
     PIMETextService.dll), taken unmodified out of the official PIME 1.3.0
     setup. The setup itself is not shipped: it would also install PIME's
     own input methods (Chewing etc.).
  3. Fetch pinned third-party files into build/cache (PIME setup, PIME's
     license, Python embeddable zip, Inno Setup's Traditional Chinese
     messages) and verify their SHA-256 (and the PSF signature on python.exe).
  4. Compile installer/smartime.iss with Inno Setup's ISCC.

Run:  .venv\\Scripts\\python tools\\build_installer.py
Needs Inno Setup 6 (ISCC). Default location: build/tools/InnoSetup6/ISCC.exe;
override with the ISCC environment variable.
"""

from __future__ import annotations

import hashlib
import lzma
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
CACHE = BUILD / "cache"
STAGE = BUILD / "installer-stage"
DIST = ROOT / "dist"

PYTHON_VERSION = "3.13.16"
PIME_COMMIT = "26fcf6ac8874e76b8f75f6826811b03bfdfc2e89"  # tag v1.3.0-stable
DOWNLOADS = {
    # name: (url, sha256)
    "PIME-1.3.0-stable-setup.exe": (
        "https://github.com/EasyIME/PIME/releases/download/v1.3.0-stable/PIME-1.3.0-stable-setup.exe",
        "6b2e288b95085a52f378f023fb17128f5b1389a3cdae078c7e4d47c1b4e9dc35",
    ),
    "PIME-LGPL-2.1.txt": (
        f"https://raw.githubusercontent.com/EasyIME/PIME/{PIME_COMMIT}/LGPL-2.0.txt",
        "a1a33180d02960ab1c5de36cf20b1a2f0fe9888d83826ad263da5db52f1b183b",
    ),
    f"python-{PYTHON_VERSION}-embed-amd64.zip": (
        f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip",
        "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297",
    ),
    "ChineseTraditional.isl": (
        "https://raw.githubusercontent.com/jrsoftware/issrc/6ef32198ef1f7b7b375cd4b6b90896c2a58eb4c2"
        "/Files/Languages/ChineseTraditional.isl",
        None,  # verified below by content (text file, pinned by commit)
    ),
}
# The PIME core files inside the official setup (identical to what it installs).
PIME_CORE = {
    # path under <PIME>: sha256
    "PIMELauncher.exe": "c6da2c6545e902511087993ccd9002a50e14c1f26ea6be35a280814f8db6786c",
    "x64/PIMETextService.dll": "00e3a27cbc3c038b745e9fe4b3e74e433347f84125f9ab92730d239b5e9858a4",
    "x86/PIMETextService.dll": "7b77e8d0cdc2052b1da54ac212cb48bea391930811b4020c3e0773f18b9fd1fb",
}
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")
UTF8_BOM = b"\xef\xbb\xbf"


def product() -> tuple[str, str]:
    text = (ROOT / "src" / "smartime" / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__ = "([^"]+)"', text).group(1)
    name = re.search(r'PRODUCT_NAME = "([^"]+)"', text).group(1)
    return version, name


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str) -> Path:
    url, digest = DOWNLOADS[name]
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"[fetch] {url}")
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(url, timeout=300) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
        tmp.replace(path)
    if digest and sha256(path) != digest:
        raise SystemExit(f"checksum mismatch for {path} (delete it to re-download)")
    return path


def check_signature(path: Path, expected_subject: str) -> None:
    ps = (f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
          "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)")
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    status, _, subject = out.strip().partition("|")
    if status != "Valid" or expected_subject not in subject:
        raise SystemExit(f"bad signature on {path}: {out.strip()}")


def nsis_files(setup: Path) -> dict[str, bytes]:
    """Every file stored in an NSIS installer built with ``SetCompressor
    /SOLID lzma`` (PIME's), by SHA-256. The data after the "NullsoftInst"
    header is one raw LZMA stream (5 property bytes first); inside it each
    file is a little-endian uint32 length followed by the bytes."""
    data = setup.read_bytes()
    pos = data.find(b"\xef\xbe\xad\xdeNullsoftInst")
    if pos < 0:
        raise SystemExit(f"{setup} is not an NSIS installer")
    stream = data[pos + 24:]
    props, dict_size = stream[0], struct.unpack_from("<I", stream, 1)[0]
    lzma1 = {"id": lzma.FILTER_LZMA1, "dict_size": dict_size,
             "lc": props % 9, "lp": props // 9 % 5, "pb": props // 45}
    out = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[lzma1]).decompress(stream[5:])
    files: dict[str, bytes] = {}
    o = 0
    while o + 4 <= len(out):
        (n,) = struct.unpack_from("<I", out, o)
        blob = out[o + 4:o + 4 + n]
        files[hashlib.sha256(blob).hexdigest()] = blob
        o += 4 + n
    return files


def stage_pime_core() -> None:
    """Copy PIMELauncher.exe and both PIMETextService.dll out of the official
    PIME setup into the stage, matched and verified by SHA-256."""
    files = nsis_files(fetch("PIME-1.3.0-stable-setup.exe"))
    for rel, digest in PIME_CORE.items():
        if digest not in files:
            raise SystemExit(f"PIME core file {rel} ({digest}) not found in the PIME setup")
        dest = STAGE / "pime" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(files[digest])


def stage(version: str) -> Path:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    app = STAGE / "smartime"
    app.mkdir(parents=True)

    # Backend entry point and IME manifest/icons (what PIME looks at).
    shutil.copy2(ROOT / "backend" / "server.py", app / "server.py")
    shutil.copy2(ROOT / "backend" / "settings.py", app / "settings.py")
    shutil.copytree(ROOT / "backend" / "input_methods", app / "input_methods", ignore=IGNORE)

    # Engine sources and the system lexicon.
    shutil.copytree(ROOT / "src" / "smartime", app / "app" / "src" / "smartime", ignore=IGNORE)
    db = ROOT / "data" / "generated" / "smartime.db"
    if not db.exists():
        raise SystemExit("data/generated/smartime.db is missing; run tools/build_data.py first")
    (app / "app" / "data" / "generated").mkdir(parents=True)
    shutil.copy2(db, app / "app" / "data" / "generated" / "smartime.db")

    # Private Python runtime. The ._pth file makes the embeddable Python
    # ignore PYTHONPATH and the user's site-packages; ".." adds <smartime>.
    runtime = app / "runtime"
    with zipfile.ZipFile(fetch(f"python-{PYTHON_VERSION}-embed-amd64.zip")) as z:
        z.extractall(runtime)
    pth = next(runtime.glob("python*._pth"))
    pth.write_text(pth.read_text(encoding="ascii").rstrip("\n") + "\n..\n", encoding="ascii")
    for exe in ("python.exe", "pythonw.exe", f"python{PYTHON_VERSION.replace('.', '')[:3]}.dll"):
        check_signature(runtime / exe, "Python Software Foundation")

    # Helpers the installer/uninstaller run from <smartime>\installer.
    helpers = app / "installer"
    helpers.mkdir()
    for src in [ROOT / "scripts" / "tsf-profile.ps1", ROOT / "scripts" / "pime_backends.py",
                ROOT / "installer" / "langlist.ps1", ROOT / "installer" / "stop-backend.ps1",
                ROOT / "installer" / "pending-deletes.ps1", ROOT / "installer" / "verify.py"]:
        shutil.copy2(src, helpers / src.name)

    stage_pime_core()

    # License notices.
    lic = app / "licenses"
    lic.mkdir()
    shutil.copy2(ROOT / "LICENSE", lic / "LICENSE.txt")  # this project: Apache-2.0
    shutil.copy2(ROOT / "NOTICE", lic / "NOTICE.txt")
    shutil.copy2(ROOT / "installer" / "THIRD-PARTY-NOTICES.txt", lic / "THIRD-PARTY-NOTICES.txt")
    shutil.copy2(fetch("PIME-LGPL-2.1.txt"), lic / "PIME-LGPL-2.1.txt")
    mcb = next((ROOT / "data" / "vendor").glob("McBopomofo-*/LICENSE.txt"), None)
    if mcb is None:
        raise SystemExit("McBopomofo LICENSE.txt not found in data/vendor; run tools/build_data.py")
    shutil.copy2(mcb, lic / "McBopomofo-LICENSE.txt")
    cj = next((ROOT / "data" / "vendor").glob("Cangjie5-*/LICENSE"), None)
    if cj is None:
        raise SystemExit("Cangjie5 LICENSE not found in data/vendor; run tools/build_data.py")
    shutil.copy2(cj, lic / "Cangjie5-LICENSE.txt")

    (app / "VERSION.txt").write_text(version + "\n", encoding="ascii")
    return STAGE


def write_iss(version: str, name: str) -> Path:
    """Copy the .iss into the stage with the build values and a UTF-8 BOM
    (ISCC reads BOM-less scripts with the system ANSI code page)."""
    isl_src = fetch("ChineseTraditional.isl")
    isl_text = isl_src.read_bytes()
    if b"LanguageID=$0404" not in isl_text:
        raise SystemExit("unexpected ChineseTraditional.isl content")
    isl = STAGE / "ChineseTraditional.isl"
    isl.write_bytes(isl_text if isl_text.startswith(UTF8_BOM) else UTF8_BOM + isl_text)

    defines = "\n".join([
        f'#define AppVersion "{version}"',
        f'#define AppName "{name}"',
        f'#define StageDir "{STAGE}"',
        f'#define OutputDir "{DIST}"',
        f'#define ShaLauncher "{PIME_CORE["PIMELauncher.exe"]}"',
        f'#define ShaDll64 "{PIME_CORE["x64/PIMETextService.dll"]}"',
        f'#define ShaDll86 "{PIME_CORE["x86/PIMETextService.dll"]}"',
        "",
    ])
    body = (ROOT / "installer" / "smartime.iss").read_text(encoding="utf-8")
    iss = STAGE / "smartime.iss"
    iss.write_bytes(UTF8_BOM + (defines + body).encode("utf-8"))
    return iss


def iscc_path() -> Path:
    env = os.environ.get("ISCC")
    candidates = [Path(env)] if env else []
    candidates += [BUILD / "tools" / "InnoSetup6" / "ISCC.exe",
                   Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
                   Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"]
    for c in candidates:
        if c.is_file():
            return c
    raise SystemExit("ISCC.exe (Inno Setup 6) not found; set the ISCC environment variable")


def main() -> None:
    version, name = product()
    print(f"[build] {name} {version}")
    stage(version)
    iss = write_iss(version, name)
    DIST.mkdir(exist_ok=True)
    subprocess.run([str(iscc_path()), "/Q", str(iss)], check=True)
    out = DIST / f"ShundaIME-Setup-{version}.exe"
    print(f"[build] {out}  {out.stat().st_size / 1e6:.1f} MB  sha256={sha256(out)}")


if __name__ == "__main__":
    sys.exit(main())
