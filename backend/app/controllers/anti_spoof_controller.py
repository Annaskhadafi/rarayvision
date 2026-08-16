import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile
from backend.app.core.deps import get_current_user
from backend.app.database.models import User
from backend.app.services.anti_spoof_service import AntiSpoofService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/anti-spoof", tags=["Anti-Spoofing & Liveness"])

@router.get("/models")
def get_available_anti_spoof_models():
    """
    Returns available Anti-Spoofing models, architectures, and capabilities.
    """
    return {
        "status": "success",
        "models": [
            {
                "key": "raray_native",
                "name": "Raray Vision Native (MiniFASNetV2 ONNX)",
                "framework": "ONNX Runtime",
                "description": "Standard fast ONNX engine deployed natively in Raray Vision with 80x80 crop input.",
                "crop_scale": 2.7,
                "input_shape": [1, 3, 80, 80]
            },
            {
                "key": "uniface_v2",
                "name": "UniFace MiniFASNet V2",
                "framework": "UniFace / ONNX Runtime",
                "description": "Official UniFace v4.0 MiniFASNet V2 with multi-scale contextual face crop.",
                "crop_scale": 2.7,
                "input_shape": [1, 3, 80, 80]
            },
            {
                "key": "uniface_v1se",
                "name": "UniFace MiniFASNet V1SE (SE-Attention)",
                "framework": "UniFace / ONNX Runtime",
                "description": "UniFace Squeeze-and-Excitation enhanced architecture with wide context (scale 4.0).",
                "crop_scale": 4.0,
                "input_shape": [1, 3, 80, 80]
            }
        ]
    }

@router.post("/compare")
async def compare_anti_spoof_models(
    file: UploadFile = File(..., description="Image file (JPG, PNG, WebP) of the face to evaluate"),
    current_user: User = Depends(get_current_user)
):
    """
    Evaluates an uploaded face image across all 3 Anti-Spoofing models concurrently
    and returns a side-by-side comparison including Real/Spoof classification,
    confidence score (%), execution latency (ms), and consensus agreement.
    """
    try:
        content = await file.read()
        if not content or len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        res = AntiSpoofService.compare_all(content)
        return {
            "status": "success",
            "filename": file.filename,
            "data": res
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[AntiSpoofController] compare error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Anti-spoofing comparison failed: {str(e)}")

@router.post("/predict")
async def predict_single_anti_spoof(
    file: UploadFile = File(..., description="Face image file"),
    model_key: str = Form("uniface_v2", description="Model choice: 'raray_native', 'uniface_v2', or 'uniface_v1se'"),
    current_user: User = Depends(get_current_user)
):
    """
    Evaluates an uploaded face image using a single chosen Anti-Spoofing model.
    """
    try:
        import cv2
        import numpy as np

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file uploaded.")

        nparr = np.frombuffer(content, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image format.")

        bbox = AntiSpoofService.detect_face_bbox(img)

        if model_key == "raray_native":
            pred = AntiSpoofService.predict_native_model(img, bbox)
        elif model_key == "uniface_v1se":
            pred = AntiSpoofService.predict_uniface_v1se(img, bbox)
        else:
            pred = AntiSpoofService.predict_uniface_v2(img, bbox)

        return {
            "status": "success",
            "filename": file.filename,
            "face_bbox": [int(x) for x in bbox],
            "prediction": pred
        }
    except Exception as e:
        logger.error(f"[AntiSpoofController] predict error: {e}")
        raise HTTPException(status_code=500, detail=f"Anti-spoofing prediction failed: {str(e)}")

@router.post("/uniface-v2")
async def check_uniface_v2(
    file: UploadFile = File(..., description="Face image file to inspect with UniFace MiniFASNet V2"),
    current_user: User = Depends(get_current_user)
):
    """
    Dedicated endpoint for UniFace MiniFASNet V2 Anti-Spoofing.
    Evaluates if the uploaded face is REAL or a SPOOF attack.
    """
    try:
        import cv2
        import numpy as np

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file uploaded.")

        nparr = np.frombuffer(content, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image format.")

        bbox = AntiSpoofService.detect_face_bbox(img)
        pred = AntiSpoofService.predict_uniface_v2(img, bbox)

        return {
            "status": "success",
            "filename": file.filename,
            "face_bbox": {
                "x1": int(bbox[0]),
                "y1": int(bbox[1]),
                "x2": int(bbox[2]),
                "y2": int(bbox[3])
            },
            "is_real": pred["is_real"],
            "verdict": pred["verdict"],
            "confidence": pred["confidence"],
            "score_raw": pred["score_raw"],
            "latency_ms": pred["latency_ms"]
        }
    except Exception as e:
        logger.error(f"[AntiSpoofController] uniface-v2 error: {e}")
        raise HTTPException(status_code=500, detail=f"UniFace V2 inspection failed: {str(e)}")
