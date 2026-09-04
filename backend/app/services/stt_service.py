import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

_MODELS = {
    "fw-base-int8": {"engine": "faster-whisper", "model": "base", "compute_type": "int8"},
    "fw-small-int8": {"engine": "faster-whisper", "model": "small", "compute_type": "int8"},
}
_loaded = {}
_load_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


def model_catalog():
    return [
        {
            "id": model_id,
            "engine": spec["engine"],
            "model": spec["model"],
            "compute_type": spec["compute_type"],
            "language": "id",
            "loaded": model_id in _loaded,
        }
        for model_id, spec in _MODELS.items()
    ]


def _get_model(model_id: str, cpu_threads: int):
    if model_id not in _MODELS:
        raise ValueError(f"Unknown STT model: {model_id}")
    if model_id not in _loaded:
        with _load_lock:
            if model_id not in _loaded:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError("faster-whisper belum terpasang") from exc
                model = _MODELS[model_id]
                _loaded[model_id] = WhisperModel(
                    model["model"],
                    device="cpu",
                    compute_type=model["compute_type"],
                    cpu_threads=max(1, min(int(cpu_threads), os.cpu_count() or 1)),
                )
    return _loaded[model_id]


def transcribe_sync(audio_bytes: bytes, model_id: str, language: str = "id", cpu_threads: int = 2):
    started = time.perf_counter()
    model = _get_model(model_id, cpu_threads)
    segments, info = model.transcribe(
        io.BytesIO(audio_bytes),
        language=language,
        task="transcribe",
        beam_size=1,
        vad_filter=True,
    )
    items = list(segments)
    text = " ".join(segment.text.strip() for segment in items).strip()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    duration = float(getattr(info, "duration", 0) or 0)
    return {
        "text": text,
        "language": getattr(info, "language", language),
        "duration_seconds": round(duration, 3),
        "processing_ms": elapsed_ms,
        "rtf": round((elapsed_ms / 1000) / duration, 3) if duration else None,
        "model": model_id,
    }


def transcribe(audio_bytes: bytes, model_id: str, language: str = "id", cpu_threads: int = 2):
    return _executor.submit(transcribe_sync, audio_bytes, model_id, language, cpu_threads).result()
