"""Speech recognition engines. Heavy imports happen inside the classes, so
importing this module is cheap."""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

from . import models

log = logging.getLogger(__name__)
SAMPLE_RATE = 16000


def _add_cuda_dll_dirs() -> None:
    """CTranslate2 loads cuBLAS/cuDNN at run time; the nvidia-* wheels put
    the DLLs under site-packages/nvidia/*/bin, which is not on the DLL path."""
    for base in map(Path, sys.path):
        nv = base / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in nv.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            except OSError:
                pass


# What CTranslate2 loads when Whisper runs on the GPU. Seeing the GPU is not
# enough: without these the model loads fine and fails at the first use.
CUDA_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn_ops64_9.dll", "cudnn_cnn64_9.dll")


def cuda_available() -> bool:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() <= 0:
            return False
    except Exception:  # noqa: BLE001
        return False
    _add_cuda_dll_dirs()
    for dll in CUDA_DLLS:
        try:
            ctypes.WinDLL(dll)
        except OSError:
            log.warning("NVIDIA GPU found but %s is missing; using the CPU", dll)
            return False
    return True


class BreezeEngine:
    """Breeze-ASR-25 (Whisper large-v2 fine-tuned for Taiwanese Mandarin and
    code-switching) through faster-whisper / CTranslate2."""

    name = "Breeze-ASR-25"

    def __init__(self, device: str = "cuda"):
        _add_cuda_dll_dirs()
        from faster_whisper import WhisperModel

        compute = "float16" if device == "cuda" else "int8"
        self.model = WhisperModel(str(models.model_path("breeze")), device=device, compute_type=compute)
        self.device = device

    def transcribe(self, audio, hotwords: str = "") -> str:
        segments, _ = self.model.transcribe(
            audio,
            language="zh",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            hotwords=hotwords or None,
        )
        return "".join(s.text for s in segments).strip()


class SenseVoiceEngine:
    """SenseVoice Small (int8) through sherpa-onnx; fast on the CPU."""

    name = "SenseVoice"

    def __init__(self, threads: int = 4):
        import sherpa_onnx

        d = models.model_path("sensevoice")
        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(d / "model.int8.onnx"),
            tokens=str(d / "tokens.txt"),
            num_threads=threads,
            use_itn=True,  # numbers, punctuation
            language="auto",
        )

    def transcribe(self, audio, hotwords: str = "") -> str:
        stream = self.rec.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio)
        self.rec.decode_stream(stream)
        return stream.result.text.strip()


def create(engine: str):
    """engine: "auto" | "breeze" | "sensevoice". Raises with a readable
    message when nothing usable is installed."""
    want = engine
    if engine == "auto":
        if models.installed("breeze") and cuda_available():
            want = "breeze"
        elif models.installed("sensevoice"):
            want = "sensevoice"
        elif models.installed("breeze"):
            want = "breeze"  # works on the CPU, just slowly
        else:
            raise RuntimeError("還沒有下載語音模型：請到設定 > 語音輸入 下載")
    if want == "breeze":
        if not models.installed("breeze"):
            raise RuntimeError("Breeze-ASR-25 還沒下載")
        return BreezeEngine("cuda" if cuda_available() else "cpu")
    if want == "sensevoice":
        if not models.installed("sensevoice"):
            raise RuntimeError("SenseVoice 還沒下載")
        return SenseVoiceEngine()
    raise RuntimeError(f"unknown engine {engine}")
