import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.app.core.deps import get_current_user
from backend.app.database import database as db
from backend.app.database.models import STTConfig, User
from backend.app.services.stt_service import model_catalog, transcribe

router = APIRouter(
    prefix="/api/v1/stt",
    tags=["Speech to Text"],
)
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def _config(session: Session) -> STTConfig:
    config = session.query(STTConfig).first()
    if not config:
        config = STTConfig()
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


@router.get(
    "/models",
    summary="List available CPU STT models",
    description="Returns the locally supported Bahasa Indonesia speech-to-text models and their loaded state.",
)
def get_models(current_user: User = Depends(get_current_user)):
    return {"status": "success", "models": model_catalog()}


@router.get(
    "/config",
    summary="Get active STT configuration",
    description="Returns the global STT model and CPU settings used by public transcription requests.",
)
def get_config(session: Session = Depends(db.get_db), current_user: User = Depends(get_current_user)):
    config = _config(session)
    return {"status": "success", "config": {
        "active_model": config.active_model,
        "language": config.language,
        "cpu_threads": config.cpu_threads,
    }}


@router.patch(
    "/config",
    summary="Update active STT configuration",
    description="Updates the global active model, language, and CPU thread limit. Fields are sent as multipart form data.",
)
def update_config(
    active_model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    cpu_threads: Optional[int] = Form(None),
    session: Session = Depends(db.get_db),
    current_user: User = Depends(get_current_user),
):
    if active_model is not None and active_model not in {item["id"] for item in model_catalog()}:
        raise HTTPException(status_code=400, detail="Model STT tidak tersedia")
    config = _config(session)
    if active_model is not None:
        config.active_model = active_model
    if language is not None:
        config.language = language[:10]
    if cpu_threads is not None:
        config.cpu_threads = max(1, min(cpu_threads, 16))
    session.commit()
    session.refresh(config)
    return {"status": "success", "config": {
        "active_model": config.active_model,
        "language": config.language,
        "cpu_threads": config.cpu_threads,
    }}


@router.post(
    "/transcriptions",
    summary="Transcribe audio with the active model",
    description=(
        "Uploads an audio file and returns Indonesian text. "
        "The endpoint always uses the configured active model; authentication accepts the existing Raray JWT or API key. "
        "Maximum upload size is 25 MB."
    ),
)
async def transcribe_audio(
    file: UploadFile = File(...),
    session: Session = Depends(db.get_db),
    current_user: User = Depends(get_current_user),
):
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Audio kosong")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio maksimal 25 MB")
    config = _config(session)
    selected_model = config.active_model
    if selected_model not in {item["id"] for item in model_catalog()}:
        raise HTTPException(status_code=400, detail="Model STT tidak tersedia")
    try:
        result = await asyncio.to_thread(transcribe, audio, selected_model, config.language, config.cpu_threads)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "success", "result": result}


@router.post(
    "/benchmark",
    summary="Compare selected CPU STT models",
    description=(
        "Runs one audio sample sequentially through up to four selected models and returns transcript, processing time, "
        "audio duration, and real-time factor (RTF). This endpoint is intended for the authenticated STT Lab."
    ),
)
async def benchmark_audio(
    file: UploadFile = File(...),
    models: str = Form("fw-base-int8,fw-small-int8"),
    session: Session = Depends(db.get_db),
    current_user: User = Depends(get_current_user),
):
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Audio kosong")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio maksimal 25 MB")
    try:
        requested = json.loads(models) if models.startswith("[") else [item.strip() for item in models.split(",")]
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Daftar model tidak valid") from exc
    available = {item["id"] for item in model_catalog()}
    selected = list(dict.fromkeys(requested))[:4]
    if not selected or any(model_id not in available for model_id in selected):
        raise HTTPException(status_code=400, detail="Model STT tidak tersedia")
    config = _config(session)
    results = []
    for model_id in selected:
        try:
            results.append(await asyncio.to_thread(transcribe, audio, model_id, config.language, config.cpu_threads))
        except Exception as exc:
            results.append({"model": model_id, "error": str(exc)})
    return {"status": "success", "results": results}
