import os
import cv2
import time
import json
import zipfile
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image
import io

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

try:
    from backend.app.core.config import BASE_DIR
    from backend.app.database.database import SessionLocal
    from backend.app.database.models import MLModel
except ImportError:
    from app.core.config import BASE_DIR
    from app.database.database import SessionLocal
    from app.database.models import MLModel

CLASS_COLORS = [
    (0, 215, 255),   # Gold / Yellow
    (255, 105, 180), # Hot Pink
    (50, 205, 50),   # Lime Green
    (30, 144, 255),  # Dodger Blue
    (255, 140, 0),   # Dark Orange
    (147, 112, 219), # Medium Purple
    (0, 250, 154),   # Medium Spring Green
    (220, 20, 60),   # Crimson
    (0, 191, 255),   # Deep Sky Blue
    (255, 215, 0)    # Gold
]

class DetectionService:
    def __init__(self):
        self.active_model_id: Optional[int] = None
        self.previous_active_model_id: Optional[int] = None
        self.active_model_name: str = "yolov8n-default"
        self.active_model_version: str = "v1.0.0"
        self.active_classes: List[str] = []
        self.model_instance = None
        self.is_loaded = False
        self._model_cache = {}
        
        # Models directory
        self.models_storage_dir = os.path.join(BASE_DIR, "uploads", "models")
        self.evaluations_dir = os.path.join(BASE_DIR, "uploads", "evaluations")
        os.makedirs(self.models_storage_dir, exist_ok=True)
        os.makedirs(self.evaluations_dir, exist_ok=True)

        self.init_model()

    def init_model(self):
        """Load the active model from DB, or fallback to default yolov8n.pt"""
        db = SessionLocal()
        try:
            active = db.query(MLModel).filter(MLModel.is_active == True).first()
            if active and os.path.exists(active.model_path):
                self._load_from_path(active.model_path, active.id, active.name, active.version, active.classes)
            else:
                root_yolo = os.path.join(os.path.dirname(BASE_DIR), "yolov8n.pt")
                if not os.path.exists(root_yolo):
                    root_yolo = os.path.join(BASE_DIR, "yolov8n.pt")
                
                if os.path.exists(root_yolo) and YOLO:
                    self._load_from_path(root_yolo, None, "YOLOv8n Base", "v8n-default", None)
                    if not active:
                        try:
                            default_rec = MLModel(
                                name="YOLOv8n Base",
                                version="v8n-default",
                                task_type="detection",
                                framework="yolo",
                                model_path=root_yolo,
                                classes=json.dumps(list(self.model_instance.names.values()) if hasattr(self.model_instance, 'names') else []),
                                is_active=True,
                                description="Pretrained YOLOv8 nano model"
                            )
                            db.add(default_rec)
                            db.commit()
                            db.refresh(default_rec)
                            self.active_model_id = default_rec.id
                        except Exception:
                            db.rollback()
        except Exception as e:
            print(f"[DetectionService] Error initializing model from DB: {e}")
        finally:
            db.close()

    def _load_from_path(self, path: str, model_id: Optional[int], name: str, version: str, classes_json: Optional[str]):
        """Load YOLO (.pt or .onnx) model weights into memory."""
        try:
            if YOLO:
                self.model_instance = YOLO(path)
                self.active_model_id = model_id
                self.active_model_name = name
                self.active_model_version = version
                if hasattr(self.model_instance, "names") and self.model_instance.names:
                    self.active_classes = list(self.model_instance.names.values())
                elif classes_json:
                    self.active_classes = json.loads(classes_json)
                self.is_loaded = True
                print(f"[DetectionService] Loaded model '{name}' ({version}) from {path}")
            else:
                print("[DetectionService] Ultralytics not installed or failed to import.")
        except Exception as e:
            print(f"[DetectionService] Failed to load model from {path}: {e}")

    def get_model(self, model_id: Optional[int] = None, db = None) -> Tuple[Any, Optional[int], str, str, List[str]]:
        """
        Retrieve model instance for inference. If model_id is None, returns global active model.
        Otherwise, loads model by ID from memory cache or disk weights.
        Returns (model_instance, model_id, model_name, model_version, classes_list)
        """
        if model_id is None or (self.active_model_id is not None and model_id == self.active_model_id):
            if not self.is_loaded or self.model_instance is None:
                self.init_model()
            return self.model_instance, self.active_model_id, self.active_model_name, self.active_model_version, self.active_classes

        if model_id in self._model_cache:
            return self._model_cache[model_id]

        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True
        try:
            m = db.query(MLModel).filter(MLModel.id == model_id).first()
            if not m:
                raise ValueError(f"Model ID {model_id} not found in database")

            m_path = m.onnx_path if (m.framework == 'onnx' and m.onnx_path and os.path.exists(m.onnx_path)) else m.model_path
            if not os.path.exists(m_path):
                raise FileNotFoundError(f"Model weights file not found at {m_path}")

            if not YOLO:
                raise RuntimeError("Ultralytics YOLO not installed")

            inst = YOLO(m_path)
            classes = []
            if hasattr(inst, 'names') and inst.names:
                classes = list(inst.names.values())
            elif m.classes:
                classes = json.loads(m.classes)

            entry = (inst, m.id, m.name, m.version, classes)
            self._model_cache[model_id] = entry
            return entry
        finally:
            if should_close:
                db.close()

    def invalidate_model_cache(self, model_id: int):
        """Remove a model from cache when updated or deleted."""
        if model_id in self._model_cache:
            del self._model_cache[model_id]
        if self.active_model_id == model_id:
            self.model_instance = None
            self.is_loaded = False

    def hot_swap_model(self, model_id: int, db) -> Dict[str, Any]:
        """Switch the active model in DB and reload memory weights without server downtime."""
        target_model = db.query(MLModel).filter(MLModel.id == model_id).first()
        if not target_model:
            return {"success": False, "error": f"Model with ID {model_id} not found"}

        model_file = target_model.onnx_path if (target_model.framework == 'onnx' and target_model.onnx_path and os.path.exists(target_model.onnx_path)) else target_model.model_path

        if not os.path.exists(model_file):
            return {"success": False, "error": f"Model file does not exist at {model_file}"}

        # Track previous active model for 1-click rollback
        current_active = db.query(MLModel).filter(MLModel.is_active == True).first()
        if current_active and current_active.id != model_id:
            self.previous_active_model_id = current_active.id

        # Set all to inactive, activate target
        db.query(MLModel).update({MLModel.is_active: False})
        target_model.is_active = True
        db.commit()

        # Reload in memory
        self._load_from_path(
            model_file,
            target_model.id,
            target_model.name,
            target_model.version,
            target_model.classes
        )

        return {
            "success": True,
            "message": f"Berhasil mengaktifkan model {target_model.name} ({target_model.version})",
            "previous_model_id": self.previous_active_model_id,
            "active_model": {
                "id": target_model.id,
                "name": target_model.name,
                "version": target_model.version,
                "framework": target_model.framework,
                "classes": self.active_classes
            }
        }

    def rollback_model(self, db) -> Dict[str, Any]:
        """Instant fail-safe rollback to previous active model."""
        if not self.previous_active_model_id:
            # Fallback to the second newest model in DB
            prev = db.query(MLModel).filter(MLModel.is_active == False).order_by(MLModel.updated_at.desc()).first()
            if prev:
                return self.hot_swap_model(prev.id, db)
            return {"success": False, "error": "Tidak ada riwayat model sebelumnya untuk di-rollback."}
        
        return self.hot_swap_model(self.previous_active_model_id, db)

    def export_to_onnx(self, model_id: int, db) -> Dict[str, Any]:
        """Export a PyTorch .pt model to ONNX for accelerated CPU/GPU inference."""
        model_rec = db.query(MLModel).filter(MLModel.id == model_id).first()
        if not model_rec:
            return {"success": False, "error": "Model tidak ditemukan"}

        if not os.path.exists(model_rec.model_path):
            return {"success": False, "error": f"File model tidak ditemukan di {model_rec.model_path}"}

        try:
            y = YOLO(model_rec.model_path)
            exported_path = y.export(format="onnx", imgsz=640, simplify=True)
            model_rec.onnx_path = exported_path
            db.commit()
            return {
                "success": True,
                "onnx_path": exported_path,
                "message": f"Model berhasil diexport ke format ONNX: {os.path.basename(exported_path)}"
            }
        except Exception as e:
            return {"success": False, "error": f"Export ke ONNX gagal: {str(e)}"}

    def check_image_quality(self, img_bgr: np.ndarray) -> Dict[str, Any]:
        """
        CV-Ops Image Quality Gate:
        - Laplacian variance: checks for blurriness / motion blur.
        - Mean intensity: checks for underexposure (dark) or overexposure (glare).
        """
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        blur_score = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1)
        brightness = round(float(np.mean(gray)), 1)

        is_blurry = blur_score < 35.0
        is_dark = brightness < 28.0
        is_overexposed = brightness > 238.0
        is_usable = not (is_blurry or is_dark or is_overexposed)

        warnings = []
        if is_blurry:
            warnings.append(f"Gambar buram (skor: {blur_score} < 35). Hasil deteksi mungkin tidak akurat.")
        if is_dark:
            warnings.append(f"Gambar terlalu gelap (kecerahan: {brightness} < 28).")
        if is_overexposed:
            warnings.append(f"Gambar terlalu silau/terang (kecerahan: {brightness} > 238).")

        return {
            "is_usable": is_usable,
            "is_blurry": is_blurry,
            "is_dark": is_dark,
            "is_overexposed": is_overexposed,
            "blur_score": blur_score,
            "brightness": brightness,
            "warnings": warnings
        }

    def predict(
        self,
        image_bytes: bytes,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        model_id: Optional[int] = None,
        db = None
    ) -> Dict[str, Any]:
        """
        Run inference on image bytes, draw bounding boxes, and compute metrics.
        Can run using the active model or any specific model_id.
        """
        model_inst, m_id, m_name, m_version, m_classes = self.get_model(model_id, db=db)
        if model_inst is None:
            raise RuntimeError(f"No model available for inference (model_id={model_id}).")

        np_arr = np.frombuffer(image_bytes, np.uint8)
        img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise ValueError("Failed to decode image from provided bytes.")

        h, w = img_bgr.shape[:2]

        # CV-Ops Image Quality Pre-check
        quality = self.check_image_quality(img_bgr)

        start_time = time.time()
        results = model_inst.predict(
            source=img_bgr,
            conf=conf_threshold,
            iou=iou_threshold,
            verbose=False
        )
        latency_ms = round((time.time() - start_time) * 1000.0, 2)

        detections = []
        top_conf = 0.0
        annotated_bgr = img_bgr.copy()

        if len(results) > 0:
            result = results[0]
            boxes = result.boxes
            names = result.names or {}

            if boxes is not None and len(boxes) > 0:
                for i, box in enumerate(boxes):
                    cls_id = int(box.cls[0].item())
                    label = names.get(cls_id, str(cls_id))
                    conf = float(box.conf[0].item())
                    coords = box.xyxy[0].tolist()
                    
                    x1, y1, x2, y2 = [int(v) for v in coords]
                    x1 = max(0, min(w, x1))
                    y1 = max(0, min(h, y1))
                    x2 = max(0, min(w, x2))
                    y2 = max(0, min(h, y2))

                    if conf > top_conf:
                        top_conf = conf

                    detections.append({
                        "id": i,
                        "class_id": cls_id,
                        "label": label,
                        "confidence": round(conf, 4),
                        "box": [x1, y1, x2, y2],
                        "normalized_box": [
                            round(x1 / w, 4),
                            round(y1 / h, 4),
                            round(x2 / w, 4),
                            round(y2 / h, 4)
                        ]
                    })

                    color = CLASS_COLORS[cls_id % len(CLASS_COLORS)]
                    cv2.rectangle(annotated_bgr, (x1, y1), (x2, y2), color, 2)

                    tag = f"{label} {conf*100:.1f}%"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = max(0.4, min(0.8, w / 1000.0))
                    thickness = 1
                    (tw, th), baseline = cv2.getTextSize(tag, font, font_scale, thickness)

                    bg_y1 = max(0, y1 - th - baseline - 4)
                    bg_y2 = y1
                    cv2.rectangle(annotated_bgr, (x1, bg_y1), (x1 + tw + 6, bg_y2), color, -1)
                    cv2.putText(
                        annotated_bgr,
                        tag,
                        (x1 + 3, bg_y2 - baseline - 2),
                        font,
                        font_scale,
                        (0, 0, 0),
                        thickness,
                        cv2.LINE_AA
                    )

        # Draw quality warning banner on annotated image if degraded
        if not quality["is_usable"]:
            warn_text = "Quality Warning: " + (quality["warnings"][0] if quality["warnings"] else "Poor lighting/blur")
            cv2.putText(annotated_bgr, warn_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        _, enc = cv2.imencode(".jpg", annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        annotated_bytes = enc.tobytes()

        return {
            "model_id": m_id,
            "model_name": m_name,
            "model_version": m_version,
            "detections": detections,
            "detection_count": len(detections),
            "top_confidence": round(top_conf, 4),
            "latency_ms": latency_ms,
            "image_width": w,
            "image_height": h,
            "quality": quality,
            "annotated_bytes": annotated_bytes
        }

    def process_evaluation_archive(self, zip_path: str, model_id: int) -> Dict[str, Any]:
        """Extract training results.zip and parse evaluation metrics."""
        dest_dir = os.path.join(self.evaluations_dir, f"model_{model_id}")
        os.makedirs(dest_dir, exist_ok=True)

        extracted_files = []
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for member in zip_ref.namelist():
                filename = os.path.basename(member)
                if not filename:
                    continue
                target_path = os.path.join(dest_dir, filename)
                with zip_ref.open(member) as source, open(target_path, "wb") as target:
                    target.write(source.read())
                extracted_files.append(filename)

        metrics = {
            "map50": 0.0,
            "map50_95": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "epochs": 0
        }
        visuals = {}

        csv_path = os.path.join(dest_dir, "results.csv")
        if os.path.exists(csv_path):
            try:
                import csv
                with open(csv_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    if rows:
                        last_row = rows[-1]
                        metrics["epochs"] = len(rows)
                        cleaned = {k.strip(): float(v.strip()) for k, v in last_row.items() if v.strip() and k.strip() != 'epoch'}
                        metrics["map50"] = cleaned.get("metrics/mAP50(B)", cleaned.get("mAP50", 0.0))
                        metrics["map50_95"] = cleaned.get("metrics/mAP50-95(B)", cleaned.get("mAP50-95", 0.0))
                        metrics["precision"] = cleaned.get("metrics/precision(B)", cleaned.get("precision", 0.0))
                        metrics["recall"] = cleaned.get("metrics/recall(B)", cleaned.get("recall", 0.0))
            except Exception as e:
                print(f"[DetectionService] Error parsing results.csv: {e}")

        eval_keys = [
            ("confusion_matrix", "confusion_matrix.png"),
            ("confusion_matrix_norm", "confusion_matrix_normalized.png"),
            ("pr_curve", "PR_curve.png"),
            ("f1_curve", "F1_curve.png"),
            ("results_png", "results.png"),
            ("labels", "labels.jpg"),
            ("val_pred", "val_batch0_pred.jpg")
        ]
        for key, fname in eval_keys:
            if fname in extracted_files or os.path.exists(os.path.join(dest_dir, fname)):
                visuals[key] = f"/uploads/evaluations/model_{model_id}/{fname}"

        return {
            "evaluation_dir": dest_dir,
            "metrics": metrics,
            "visuals": visuals
        }


# Singleton instance

    def predict_video(
        self,
        video_bytes: bytes,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        max_duration_sec: int = 60,
        model_id: Optional[int] = None,
        db = None
    ) -> Dict[str, Any]:
        """
        Process an uploaded video file frame-by-frame using the specified model (or active model),
        draw bounding boxes, and encode to web-compatible MP4 (H.264).
        """
        import subprocess
        import uuid

        model_inst, m_id, m_name, m_version, m_classes = self.get_model(model_id, db=db)
        if model_inst is None:
            raise RuntimeError(f"No model available for video inference (model_id={model_id}).")

        upload_dir = os.path.join(BASE_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        session_id = uuid.uuid4().hex[:8]
        temp_in = os.path.join(upload_dir, f"in_{session_id}.mp4")
        temp_raw_out = os.path.join(upload_dir, f"raw_{session_id}.mp4")
        final_web_out = os.path.join(upload_dir, f"video_{session_id}.mp4")

        with open(temp_in, "wb") as f:
            f.write(video_bytes)

        cap = cv2.VideoCapture(temp_in)
        if not cap.isOpened():
            if os.path.exists(temp_in): os.remove(temp_in)
            raise ValueError("Failed to open uploaded video.")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        max_frames = int(fps * max_duration_sec)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(temp_raw_out, fourcc, fps, (width, height))

        processed = 0
        total_detections = 0
        start_time = time.time()

        try:
            while cap.isOpened() and processed < max_frames:
                ret, frame = cap.read()
                if not ret:
                    break

                results = model_inst.predict(
                    source=frame,
                    conf=conf_threshold,
                    iou=iou_threshold,
                    verbose=False
                )

                if len(results) > 0 and results[0].boxes is not None:
                    boxes = results[0].boxes
                    names = results[0].names or {}
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        conf = float(box.conf[0].item())
                        label = names.get(cls_id, str(cls_id))
                        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]

                        color = CLASS_COLORS[cls_id % len(CLASS_COLORS)]
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        tag = f"{label} {conf*100:.0f}%"
                        cv2.putText(frame, tag, (x1 + 2, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
                        total_detections += 1

                writer.write(frame)
                processed += 1
        finally:
            cap.release()
            writer.release()
            if os.path.exists(temp_in):
                os.remove(temp_in)

        # Transcode to web-ready H.264 via FFmpeg
        final_filename = f"raw_{session_id}.mp4"
        try:
            cmd = [
                "ffmpeg", "-y", "-i", temp_raw_out,
                "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", "-an", final_web_out
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if res.returncode == 0 and os.path.exists(final_web_out):
                final_filename = f"video_{session_id}.mp4"
                if os.path.exists(temp_raw_out):
                    os.remove(temp_raw_out)
        except Exception:
            pass

        duration_sec = round(processed / fps, 2) if fps > 0 else 0
        total_time_ms = round((time.time() - start_time) * 1000, 1)

        return {
            "model_id": self.active_model_id,
            "model_name": self.active_model_name,
            "model_version": self.active_model_version,
            "video_url": f"/api/v1/uploads/{final_filename}",
            "processed_frames": processed,
            "total_frames": total_frames,
            "total_detections": total_detections,
            "fps": round(fps, 1),
            "duration_seconds": duration_sec,
            "processing_ms": total_time_ms
        }


# Singleton instance
detection_service = DetectionService()
