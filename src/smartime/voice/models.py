"""Speech models: where they live, whether they are installed, and how to
download them (plain HTTPS with resume; no extra packages, so the settings
app can do it on the IME's own Python).

Models are kept per user in %LOCALAPPDATA%\\SmartIME\\models (large files,
not roamed, not in the repo).
"""

from __future__ import annotations

import os
import shutil
import tarfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelInfo:
    key: str
    name: str
    description: str
    folder: str
    files: tuple[tuple[str, str, int], ...]  # (file, url, approximate size)
    archive: bool = False  # a .tar.bz2 to unpack into folder
    needs: str = ""  # marker file that must exist when installed


HF = "https://huggingface.co/SoybeanMilk/faster-whisper-Breeze-ASR-25/resolve/main/"
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
SENSEVOICE_ARCHIVE = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"

MODELS = {
    "breeze": ModelInfo(
        key="breeze",
        name="Breeze-ASR-25",
        description="聯發科針對台灣華語與中英夾雜調整（Whisper large-v2，需要 NVIDIA 顯示卡）",
        folder="breeze-asr-25-ct2",
        files=tuple((f, HF + f, size) for f, size in (
            ("config.json", 2796), ("preprocessor_config.json", 339), ("tokenizer.json", 3930832),
            ("vocabulary.json", 1068103), ("model.bin", 3086913037))),
        needs="model.bin",
    ),
    "sensevoice": ModelInfo(
        key="sensevoice",
        name="SenseVoice Small",
        description="阿里巴巴開源，中英日韓粵，CPU 也很快（不需要顯示卡）",
        folder="sensevoice-int8",
        files=((SENSEVOICE_ARCHIVE + ".tar.bz2", SHERPA + SENSEVOICE_ARCHIVE + ".tar.bz2", 165783878),),
        archive=True,
        needs="model.int8.onnx",
    ),
}


def models_dir() -> Path:
    base = os.environ.get("SMARTIME_MODELS_DIR")
    if base:
        return Path(base)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "SmartIME" / "models"


def model_path(key: str) -> Path:
    return models_dir() / MODELS[key].folder


def installed(key: str) -> bool:
    info = MODELS[key]
    return (model_path(key) / info.needs).is_file()


def status() -> dict:
    return {
        k: {"name": m.name, "description": m.description, "installed": installed(k),
            "size": sum(s for _, _, s in m.files)}
        for k, m in MODELS.items()
    }


def download(key: str, progress: Callable[[int, int], None] | None = None) -> Path:
    """Download (resuming partial files) and unpack a model. Blocking."""
    info = MODELS[key]
    target = model_path(key)
    target.mkdir(parents=True, exist_ok=True)
    total = sum(s for _, _, s in info.files)
    done = 0
    for name, url, size in info.files:
        dest = target / name if not info.archive else models_dir() / name
        part = dest.with_name(dest.name + ".part")
        if dest.exists() and (size == 0 or dest.stat().st_size >= size * 0.99):
            done += dest.stat().st_size
            if progress:
                progress(done, total)
            continue
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
        with urllib.request.urlopen(req, timeout=60) as resp:
            if have and resp.status != 206:  # server ignored Range: start over
                have = 0
            with open(part, "ab" if have else "wb") as out:
                done_file = have
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done_file += len(chunk)
                    if progress:
                        progress(done + done_file, total)
        part.replace(dest)
        done += dest.stat().st_size
        if info.archive:
            _unpack(dest, target)
            dest.unlink()
    if not installed(key):
        raise RuntimeError(f"{info.name}: download finished but {info.needs} is missing")
    return target


def _unpack(archive: Path, target: Path) -> None:
    """Extract a sherpa-onnx model archive; flatten its top folder."""
    tmp = target.with_name(target.name + ".unpack")
    shutil.rmtree(tmp, ignore_errors=True)
    with tarfile.open(archive, "r:bz2") as tar:
        tar.extractall(tmp, filter="data")
    inner = next((p for p in tmp.iterdir() if p.is_dir()), tmp)
    for item in inner.iterdir():
        shutil.move(str(item), str(target / item.name))
    shutil.rmtree(tmp, ignore_errors=True)
