"""Распознавание речи (faster-whisper, локально). Язык — русский или английский, определяется сам."""
import gc
import os
import re
import site
import wave
from pathlib import Path

from .config import WHISPER_MODEL, device


def _add_cuda_dlls():
    """На Windows библиотекам CUDA для whisper нужно показать, где лежат их DLL."""
    if os.name != "nt":
        return
    for base in site.getsitepackages():
        for sub in ("torch/lib", "nvidia/cublas/bin", "nvidia/cudnn/bin"):
            p = Path(base) / sub
            if p.exists():
                os.add_dll_directory(str(p))
                os.environ["PATH"] = str(p) + os.pathsep + os.environ["PATH"]


_add_cuda_dlls()

import numpy as np  # noqa: E402
import torch  # noqa: E402  — грузим раньше ctranslate2, чтобы его DLL CUDA уже были в процессе
from faster_whisper import WhisperModel  # noqa: E402


def _load():
    dev = device()
    if dev == "cuda":
        try:
            return WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
        except Exception as e:  # нет cuDNN/cuBLAS — работаем на процессоре
            print(f"[whisper] CUDA недоступна ({e}), переключаюсь на процессор")
    return WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")


# Фразы, которые Whisper «додумывает» на тишине и музыке
HALLUCINATIONS = re.compile(
    r"(субтитры (сделал|создавал|подогнал)|редактор субтитров|корректор|продолжение следует|"
    r"спасибо за просмотр|подписывайтесь на канал|thanks for watching|subtitles by|amara\.org)",
    re.I,
)


def _is_noise(seg) -> bool:
    if HALLUCINATIONS.search(seg.text):
        return True
    return seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0


def _read_wav(path: Path) -> np.ndarray:
    """WAV 16 кГц моно → массив. Читаем сами: свежий PyAV несовместим с faster-whisper."""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("Ожидается WAV 16 кГц, моно, 16 бит")
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(audio: Path, on_progress=None) -> tuple[list[dict], str, float]:
    """Возвращает фразы [{start, end, text}], язык и длительность."""
    model = _load()
    try:
        segments, info = model.transcribe(
            _read_wav(audio),
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )
        out = []
        for s in segments:
            text = s.text.strip()
            if text and not _is_noise(s):
                out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
            if on_progress and info.duration:
                on_progress(min(1.0, s.end / info.duration))
        return out, info.language, info.duration
    finally:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
