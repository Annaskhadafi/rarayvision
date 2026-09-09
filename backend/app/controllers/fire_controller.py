import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.app.core.deps import get_current_user
from backend.app.database.models import User
from backend.app.services.fire_service import detect_fire, fire_model_info

router = APIRouter(prefix="/api/v1/fire", tags=["Fire Detection"])
MAX_IMAGE_BYTES = 15 * 1024 * 1024


@router.get(
    "/model",
    summary="Get the active fire detection model",
    description="Returns the trained YOLO model used by the fire detection playground.",
)
def get_fire_model(current_user: User = Depends(get_current_user)):
    try:
        return {"status": "success", "data": fire_model_info()}
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/detect",
    summary="Detect fire in an image",
    description="Uploads one image and returns bounding boxes plus an annotated JPEG as a data URI.",
)
async def detect_fire_endpoint(
    image: UploadFile = File(..., description="Image JPG, JPEG, or PNG"),
    confidence: float = Form(0.35, ge=0.05, le=0.99),
    iou: float = Form(0.45, ge=0.05, le=0.99),
    current_user: User = Depends(get_current_user),
):
    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Gambar kosong")
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Ukuran gambar maksimal 15 MB")
    try:
        result = await asyncio.to_thread(detect_fire, contents, confidence, iou)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "data": result}
