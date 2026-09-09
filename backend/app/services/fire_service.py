import base64
import io
import os
import threading
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image

from backend.app.core.config import FIRE_MODEL_PATH

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

_model = None
_model_lock = threading.Lock()


def get_fire_model():
    global _model
    if _model is None:
        if YOLO is None:
            raise RuntimeError("Dependency ultralytics belum terpasang")
        if not os.path.isfile(FIRE_MODEL_PATH):
            raise FileNotFoundError(f"Model Fire tidak ditemukan: {FIRE_MODEL_PATH}")
        _model = YOLO(FIRE_MODEL_PATH)
    return _model


def fire_model_info() -> dict[str, Any]:
    model = get_fire_model()
    names = model.names
    return {
        "model": os.path.basename(FIRE_MODEL_PATH),
        "path": FIRE_MODEL_PATH,
        "classes": names if isinstance(names, dict) else dict(enumerate(names)),
    }


def _decode_image(image_bytes: bytes) -> np.ndarray:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError("File harus berupa gambar yang valid") from exc
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def detect_fire(image_bytes: bytes, confidence: float = 0.35, iou: float = 0.45) -> dict[str, Any]:
    image = _decode_image(image_bytes)
    started = time.perf_counter()

    # ponytail: satu model global + lock cukup untuk playground; pecah per-worker bila throughput CCTV diperlukan.
    with _model_lock:
        result = get_fire_model().predict(image, conf=confidence, iou=iou, verbose=False)[0]

    annotated = result.plot()
    detections = []
    names = result.names
    for box in result.boxes:
        class_id = int(box.cls[0])
        detections.append({
            "class_id": class_id,
            "class_name": names.get(class_id, str(class_id)),
            "confidence": round(float(box.conf[0]), 4),
            "bbox": [round(float(value), 1) for value in box.xyxy[0]],
        })

    ok, buffer = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise RuntimeError("Gagal membuat gambar hasil deteksi")

    return {
        "model": os.path.basename(FIRE_MODEL_PATH),
        "image_width": int(image.shape[1]),
        "image_height": int(image.shape[0]),
        "detections": detections,
        "detection_count": len(detections),
        "processing_ms": round((time.perf_counter() - started) * 1000, 1),
        "annotated_image": "data:image/jpeg;base64," + base64.b64encode(buffer).decode("ascii"),
    }
