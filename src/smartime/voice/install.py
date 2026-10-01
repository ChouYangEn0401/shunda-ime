"""Install the voice input component on a user's PC (Settings > 語音輸入 >
安裝語音元件), without admin rights:

1. copy the IME's own embeddable Python (the one running this code) to
   %LOCALAPPDATA%\\SmartIME\\voice-runtime and enable site-packages there;
2. fetch pip as a single zipapp (official bootstrap.pypa.io/pip/pip.pyz);
3. pip-install the voice packages into the runtime (binary wheels only),
   adding NVIDIA's CUDA libraries when the PC has an NVIDIA graphics card.

The typing engine never uses this runtime; it stays stdlib-only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

PIP_PYZ = "https://bootstrap.pypa.io/pip/pip.pyz"
PACKAGES = ["faster-whisper>=1.2", "sherpa-onnx>=1.12", "sounddevice>=0.5", "numpy>=2",
            "opencc-python-reimplemented>=0.1.7"]
GPU_PACKAGES = ["nvidia-cublas-cu12>=12.4", "nvidia-cudnn-cu12>=9.1,<10"]


def runtime_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "SmartIME" / "voice-runtime"


def has_nvidia_gpu() -> bool:
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_VideoController).Name -join ';'"],
            capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        return "nvidia" in out.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def install(log: Callable[[str], None], target: Path | None = None, gpu: bool | None = None) -> Path:
    """Blocking; reports progress lines through ``log``. ``target`` and
    ``gpu`` are for testing (default: the per-user folder, autodetect)."""
    target = target or runtime_dir()
    source = Path(sys.executable).resolve().parent
    if not (source / "python313._pth").exists() and not list(source.glob("python*._pth")):
        raise RuntimeError("這個功能需要從已安裝的智慧輸入法執行（找不到內建的 Python）")

    log("複製 Python 執行環境…")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "Lib"))
    site = target / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    pth = next(target.glob("python*._pth"))
    lines = [ln for ln in pth.read_text(encoding="ascii").splitlines() if ln.strip() and ln.strip() != ".."]
    lines = [ln for ln in lines if not ln.lstrip("#").strip().startswith("import site")]
    pth.write_text("\n".join(lines + ["Lib\\site-packages", "import site", ""]), encoding="ascii")

    log("下載 pip…")
    pip = target / "pip.pyz"
    with urllib.request.urlopen(PIP_PYZ, timeout=120) as resp, open(pip, "wb") as out:
        shutil.copyfileobj(resp, out)

    packages = list(PACKAGES)
    if has_nvidia_gpu() if gpu is None else gpu:
        log("偵測到 NVIDIA 顯示卡：一併安裝 CUDA 元件（約 1 GB）")
        packages += GPU_PACKAGES
    log("安裝語音套件（第一次需要幾分鐘）…")
    cmd = [str(target / "python.exe"), str(pip), "install", "--disable-pip-version-check", "--no-input",
           "--only-binary=:all:", "--target", str(site), *packages]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith(("Collecting", "Downloading", "Installing", "Successfully")):
            log(line[:160])
    if proc.wait() != 0:
        raise RuntimeError("pip 安裝失敗，詳見 %APPDATA%\\SmartIME\\logs\\settings.log")
    pip.unlink(missing_ok=True)
    log("完成")
    return target
