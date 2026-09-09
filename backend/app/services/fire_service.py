import base64
import io
import os
import subprocess
import tempfile
import threading
import time
import uuid
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
_UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")


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
    return _detect_fire_frame(image, confidence, iou, model_id, include_image)


def _detect_fire_frame(
    image: np.ndarray,
    confidence: float,
    iou: float,
    model_id: str,
    include_image: bool,
) -> dict[str, Any]:
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


def detect_fire_video(
    video_bytes: bytes,
    confidence: float = 0.35,
    iou: float = 0.45,
    model_id: str = "onnx",
) -> dict[str, Any]:
    """Detect fire in each video frame and save a browser-playable annotated video."""
    os.makedirs(_UPLOADS_DIR, exist_ok=True)
    input_path = ""
    raw_output_path = ""
    cap = None
    writer = None
    started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(suffix=".video", delete=False) as source:
            source.write(video_bytes)
            input_path = source.name

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError("File harus berupa video MP4, MOV, AVI, atau WEBM yang valid")

        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps <= 0:
            fps = 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if width <= 0 or height <= 0:
            raise ValueError("Dimensi video tidak valid")

        token = uuid.uuid4().hex[:12]
        raw_filename = f"fire_detection_{token}.mp4"
        raw_output_path = os.path.join(_UPLOADS_DIR, raw_filename)
        writer = cv2.VideoWriter(
            raw_output_path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError("Gagal membuat video hasil deteksi")

        processed_frames = 0
        fire_frames = 0
        total_detections = 0
        peak_detections = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frame_result = _detect_fire_frame(frame, confidence, iou, model_id, False)
            detections = frame_result["detections"]
            count = len(detections)
            total_detections += count
            peak_detections = max(peak_detections, count)
            if count:
                fire_frames += 1

            for detection in detections:
                x1, y1, x2, y2 = (int(value) for value in detection["bbox"])
                label = f'{detection["class_name"]} {detection["confidence"] * 100:.1f}%'
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 239), 3)
                label_width, label_height = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)[0]
                label_top = max(0, y1 - label_height - 12)
                cv2.rectangle(frame, (x1, label_top), (x1 + label_width + 10, y1), (0, 0, 239), -1)
                cv2.putText(frame, label, (x1 + 5, max(label_height + 2, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
            writer.write(frame)
            processed_frames += 1

        if processed_frames == 0:
            raise ValueError("Video tidak memiliki frame yang dapat diproses")
        cap.release()
        cap = None
        writer.release()
        writer = None

        final_filename = raw_filename
        web_filename = f"web_{raw_filename}"
        web_output_path = os.path.join(_UPLOADS_DIR, web_filename)
        try:
            transcode = subprocess.run(
                ["ffmpeg", "-y", "-i", raw_output_path, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an", web_output_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if transcode.returncode == 0 and os.path.isfile(web_output_path) and os.path.getsize(web_output_path):
                os.remove(raw_output_path)
                raw_output_path = ""
                final_filename = web_filename
        except FileNotFoundError:
            # OpenCV's mp4v output remains available when FFmpeg is not installed.
            pass

        return {
            "model_id": model_id,
            "model": os.path.basename(_MODEL_PATHS[model_id]),
            "engine": _MODEL_LABELS[model_id],
            "video_url": f"/api/v1/uploads/{final_filename}",
            "total_frames": total_frames or processed_frames,
            "processed_frames": processed_frames,
            "fire_frames": fire_frames,
            "total_detections": total_detections,
            "peak_detections": peak_detections,
            "fps": round(fps, 2),
            "duration_seconds": round(processed_frames / fps, 2),
            "processing_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.release()
        if input_path and os.path.exists(input_path):
            os.remove(input_path)
