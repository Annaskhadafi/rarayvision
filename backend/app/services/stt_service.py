import io
import os
import threading
import time
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

import logging

logger = logging.getLogger(__name__)

_MODELS = {
    "fw-base-int8": {"engine": "faster-whisper", "model": "base", "compute_type": "int8"},
    "fw-small-int8": {"engine": "faster-whisper", "model": "small", "compute_type": "int8"},
}
_loaded = {}
_load_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


def model_catalog():
    groq_key = bool(os.getenv("GROQ_API_KEY", "").strip())
    catalog = [
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
    if groq_key:
        catalog.append({
            "id": "groq-whisper",
            "engine": "groq-cloud",
            "model": "whisper-large-v3-turbo",
            "compute_type": "fp16",
            "language": "id",
            "loaded": True,
        })
    return catalog


def _get_model(model_id: str, cpu_threads: int):
    if model_id not in _MODELS:
        raise ValueError(f"Unknown STT model: {model_id}")
    if model_id not in _loaded:
        with _load_lock:
            if model_id not in _loaded:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError("faster-whisper belum terpasang di sistem Python") from exc
                model = _MODELS[model_id]
                _loaded[model_id] = WhisperModel(
                    model["model"],
                    device="cpu",
                    compute_type=model["compute_type"],
                    cpu_threads=max(1, min(int(cpu_threads), os.cpu_count() or 1)),
                )
    return _loaded[model_id]


def transcribe_groq(audio_bytes: bytes, language: str = "id") -> Dict[str, Any]:
    """Fallback ultra-cepat menggunakan Groq Whisper LPU API jika model lokal CPU bermasalah."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        raise ValueError("GROQ_API_KEY tidak dikonfigurasi untuk fallback transkripsi")

    started = time.perf_counter()
    import requests
    resp = requests.post(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {groq_key}"},
        files={"file": ("audio.webm", audio_bytes, "audio/webm")},
        data={"model": "whisper-large-v3-turbo", "language": language, "response_format": "verbose_json"},
        timeout=25
    )
    if resp.status_code == 200:
        data = resp.json()
        duration = float(data.get("duration", 0) or 0)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "text": data.get("text", "").strip(),
            "language": language,
            "duration_seconds": round(duration, 3),
            "processing_ms": elapsed_ms,
            "rtf": round((elapsed_ms / 1000) / duration, 3) if duration else None,
            "model": "groq-whisper-large-v3-turbo",
        }
    else:
        raise RuntimeError(f"Groq Whisper API error {resp.status_code}: {resp.text[:200]}")


def transcribe_sync(audio_bytes: bytes, model_id: str, language: str = "id", cpu_threads: int = 2):
    started = time.perf_counter()

    # Jika memilih Groq secara langsung
    if model_id == "groq-whisper":
        return transcribe_groq(audio_bytes, language=language)

    # 1. Coba faster-whisper lokal jika terpasang
    import tempfile
    tmp_path = None
    try:
        model = _get_model(model_id, cpu_threads)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        segments, info = model.transcribe(
            tmp_path,
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
    except Exception as local_err:
        logger.warning(f"[STT] Local faster-whisper failed ({local_err}), attempting Groq Whisper fallback...")
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        if groq_key:
            try:
                res = transcribe_groq(audio_bytes, language=language)
                res["note"] = f"Model lokal ({model_id}) dialihkan otomatis ke Groq Whisper LPU"
                return res
            except Exception as groq_err:
                logger.error(f"[STT] Groq Whisper fallback also failed: {groq_err}")
                raise RuntimeError(f"Model lokal gagal: {local_err}. Cloud fallback juga gagal: {groq_err}") from groq_err

        raise RuntimeError(
            f"Model STT lokal gagal dimuat atau diproses: {local_err}. "
            "Pastikan model Whisper sudah terunduh di server atau gunakan Web Speech API realtime."
        ) from local_err
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def transcribe(audio_bytes: bytes, model_id: str, language: str = "id", cpu_threads: int = 2):
    return _executor.submit(transcribe_sync, audio_bytes, model_id, language, cpu_threads).result()
