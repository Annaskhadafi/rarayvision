import base64
import io
import os
import threading
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image

from backend.app.core.config import FIRE_MODEL_PATH, FIRE_ONNX_MODEL_PATH

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

_MODEL_PATHS = {"onnx": FIRE_ONNX_MODEL_PATH, "pt": FIRE_MODEL_PATH}
_MODEL_LABELS = {"onnx": "ONNX Runtime (.onnx)", "pt": "PyTorch (.pt)"}
_models = {}
_model_lock = threading.Lock()


def list_fire_models() -> list[dict[str, Any]]:
    return [
        {
            "id": model_id,
            "label": _MODEL_LABELS[model_id],
            "file": os.path.basename(model_path),
            "available": os.path.isfile(model_path),
        }
        for model_id, model_path in _MODEL_PATHS.items()
    ]


def get_fire_model(model_id: str = "onnx"):
    if model_id not in _MODEL_PATHS:
        raise ValueError(f"Model Fire tidak valid: {model_id}")
    if model_id not in _models:
        if YOLO is None:
            raise RuntimeError("Dependency ultralytics belum terpasang")
        model_path = _MODEL_PATHS[model_id]
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"Model Fire tidak ditemukan: {model_path}")
        _models[model_id] = YOLO(model_path, task="detect")
    return _models[model_id]


def fire_model_info(model_id: str = "onnx") -> dict[str, Any]:
    model = get_fire_model(model_id)
    names = model.names
    return {
        "id": model_id,
        "model": os.path.basename(_MODEL_PATHS[model_id]),
        "engine": _MODEL_LABELS[model_id],
        "classes": names if isinstance(names, dict) else dict(enumerate(names)),
    }


def _decode_image(image_bytes: bytes) -> np.ndarray:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError("File harus berupa gambar yang valid") from exc
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def detect_fire(
    image_bytes: bytes,
    confidence: float = 0.35,
    iou: float = 0.45,
    model_id: str = "onnx",
    include_image: bool = True,
) -> dict[str, Any]:
    image = _decode_image(image_bytes)
    started = time.perf_counter()

    # ponytail: satu model global + lock cukup untuk playground; pecah per-worker bila throughput CCTV diperlukan.
    with _model_lock:
        result = get_fire_model(model_id).predict(
            image, conf=confidence, iou=iou, imgsz=640, verbose=False
        )[0]

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

    annotated_image = None
    if include_image:
        annotated = result.plot()
        ok, buffer = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            raise RuntimeError("Gagal membuat gambar hasil deteksi")
        annotated_image = "data:image/jpeg;base64," + base64.b64encode(buffer).decode("ascii")

    return {
        "model_id": model_id,
        "model": os.path.basename(_MODEL_PATHS[model_id]),
        "engine": _MODEL_LABELS[model_id],
        "image_width": int(image.shape[1]),
        "image_height": int(image.shape[0]),
        "detections": detections,
        "detection_count": len(detections),
        "processing_ms": round((time.perf_counter() - started) * 1000, 1),
        "annotated_image": annotated_image,
    }
