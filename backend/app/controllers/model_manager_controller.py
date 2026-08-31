"""
model_manager_controller.py — REST API for AI Model Manager

Endpoints:
  GET  /api/v1/models                    — List all models + status
  POST /api/v1/models/{id}/load          — Load model into RAM
  POST /api/v1/models/{id}/unload        — Unload model from RAM
  POST /api/v1/models/batch/load-all     — Load all models
  POST /api/v1/models/batch/unload-all   — Unload all models
  GET  /api/v1/models/system/ram         — Real-time system RAM stats
"""

import gc
import time
import threading
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel

from backend.app.core.deps import get_current_user
from backend.app.services import model_registry as registry

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

router = APIRouter(
    prefix="/api/v1/models",
    tags=["Model Manager"],
)

# ── Pydantic schemas ───────────────────────────────────────────────── #
class BatchAction(BaseModel):
    model_ids: Optional[list] = None  # None = all models

# ── Register all models on module import ─────────────────────────────#
_registration_done = False
_registration_lock = threading.Lock()

def _register_all_models():
    global _registration_done
    with _registration_lock:
        if _registration_done:
            return
        _registration_done = True

    # ── 1. InsightFace V1 (buffalo_l) ─────────────────────────────── #
    try:
        from backend.app.services import ml_service as ml
        def _load_face_v1():
            ml.get_face_app("v1")
            ml.get_spoof_session("v1")
            ml.get_emotion_session("v1")

        def _unload_face_v1():
            import backend.app.services.ml_service as _ml
            _ml._face_engines["v1"] = None
            _ml._spoof_sessions["v1"] = None
            _ml._emotion_sessions["v1"] = None

        registry.register_model(
            model_id="insightface_v1",
            name="InsightFace V1 (buffalo_l)",
            description="Face recognition engine V1: buffalo_l (ResNet-50 backbone, high accuracy). Includes 3D landmark, gender/age, ONNX anti-spoofing, emotion.",
            category="Face Recognition",
            ram_estimate_mb=850,
            load_fn=_load_face_v1,
            unload_fn=_unload_face_v1,
            icon="👤",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register insightface_v1: {e}")

    # ── 2. InsightFace V2 (buffalo_s) ─────────────────────────────── #
    try:
        from backend.app.services import ml_service as ml
        def _load_face_v2():
            ml.get_face_app("v2")
            ml.get_spoof_session("v2")

        def _unload_face_v2():
            import backend.app.services.ml_service as _ml
            _ml._face_engines["v2"] = None
            _ml._spoof_sessions["v2"] = None
            _ml._emotion_sessions["v2"] = None

        registry.register_model(
            model_id="insightface_v2",
            name="InsightFace V2 (buffalo_s)",
            description="Face recognition engine V2: buffalo_s (MobileNet, optimized for CPU speed). Faster but slightly lower accuracy than V1.",
            category="Face Recognition",
            ram_estimate_mb=400,
            load_fn=_load_face_v2,
            unload_fn=_unload_face_v2,
            icon="👤",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register insightface_v2: {e}")

    # ── 3. Anti-Spoof UniFace V2 ───────────────────────────────────── #
    try:
        from backend.app.services import anti_spoof_service as spoof

        def _load_uniface_v2():
            spoof.get_uniface_v2()

        def _unload_uniface_v2():
            import backend.app.services.anti_spoof_service as _s
            _s._uniface_v2_instance = None

        registry.register_model(
            model_id="antispoof_uniface_v2",
            name="Anti-Spoof UniFace V2 (MiniFASNet)",
            description="Liveness detection — MiniFASNet V2 from UniFace library. Detects photo/video spoofing attacks.",
            category="Anti-Spoofing",
            ram_estimate_mb=55,
            load_fn=_load_uniface_v2,
            unload_fn=_unload_uniface_v2,
            icon="🛡️",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register antispoof_uniface_v2: {e}")

    # ── 4. Anti-Spoof UniFace V1SE ─────────────────────────────────── #
    try:
        from backend.app.services import anti_spoof_service as spoof

        def _load_uniface_v1se():
            spoof.get_uniface_v1se()

        def _unload_uniface_v1se():
            import backend.app.services.anti_spoof_service as _s
            _s._uniface_v1_instance = None

        registry.register_model(
            model_id="antispoof_uniface_v1se",
            name="Anti-Spoof UniFace V1SE (MiniFASNet)",
            description="Liveness detection — MiniFASNet V1SE. Alternate anti-spoofing model with SE blocks.",
            category="Anti-Spoofing",
            ram_estimate_mb=55,
            load_fn=_load_uniface_v1se,
            unload_fn=_unload_uniface_v1se,
            icon="🛡️",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register antispoof_uniface_v1se: {e}")

    # ── 5. Anti-Spoof Native ONNX ─────────────────────────────────── #
    try:
        from backend.app.services import anti_spoof_service as spoof

        def _load_native_spoof():
            spoof.get_native_session()

        def _unload_native_spoof():
            import backend.app.services.anti_spoof_service as _s
            _s._native_session = None

        registry.register_model(
            model_id="antispoof_native_onnx",
            name="Anti-Spoof Native ONNX (MiniFASNetV2)",
            description="Liveness detection — Native ONNX session for MiniFASNetV2. Used as fallback when UniFace not available.",
            category="Anti-Spoofing",
            ram_estimate_mb=30,
            load_fn=_load_native_spoof,
            unload_fn=_unload_native_spoof,
            icon="🛡️",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register antispoof_native_onnx: {e}")

    # ── 6. YOLOv8n (HSE & Inventory detection) ───────────────────── #
    try:
        from backend.app.services import hse_service

        def _load_yolov8n():
            hse_service.get_yolo_model("yolov8n")

        def _unload_yolov8n():
            import backend.app.services.hse_service as _h
            _h._model_cache.pop("yolov8n", None)
            try:
                import backend.app.services.inventory_service as _i
                _i._model_cache.pop("yolov8n", None)
            except Exception:
                pass

        registry.register_model(
            model_id="yolov8n",
            name="YOLOv8n — Object Detection",
            description="YOLOv8 Nano. General-purpose object/person detection. Used for HSE safety zone, PPE detection, and inventory visual checks.",
            category="Computer Vision",
            ram_estimate_mb=60,
            load_fn=_load_yolov8n,
            unload_fn=_unload_yolov8n,
            icon="👁️",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register yolov8n: {e}")

    # ── 7. MediaPipe Pose Landmarker (Fall Detection) ─────────────── #
    try:
        from backend.app.services import fall_detection_service as fds

        def _load_mediapipe_pose():
            fds.get_pose_detector()

        def _unload_mediapipe_pose():
            import backend.app.services.fall_detection_service as _f
            if _f._pose_detector is not None:
                try:
                    _f._pose_detector.close()
                except Exception:
                    pass
            _f._pose_detector = None

        registry.register_model(
            model_id="mediapipe_pose",
            name="MediaPipe Pose Landmarker (Lite)",
            description="Google MediaPipe Pose Landmarker Lite — 33 body keypoints. Used for fall detection, kinematic analysis of torso angle and aspect ratio.",
            category="Computer Vision",
            ram_estimate_mb=85,
            load_fn=_load_mediapipe_pose,
            unload_fn=_unload_mediapipe_pose,
            icon="🦴",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register mediapipe_pose: {e}")

    # ── 8. Emotion Recognition ONNX ──────────────────────────────── #
    try:
        from backend.app.services import ml_service as ml

        def _load_emotion():
            ml.get_emotion_session("v1")

        def _unload_emotion():
            import backend.app.services.ml_service as _ml
            _ml._emotion_sessions["v1"] = None
            _ml._emotion_sessions["v2"] = None

        registry.register_model(
            model_id="emotion_onnx",
            name="Emotion Recognition (FER+ ONNX)",
            description="Facial emotion classifier — 8 classes (happy, sad, angry, fearful, disgusted, surprised, contempt, neutral). Used in Face AI features.",
            category="Face Recognition",
            ram_estimate_mb=90,
            load_fn=_load_emotion,
            unload_fn=_unload_emotion,
            icon="😊",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register emotion_onnx: {e}")

    # ── 9. FastEmbed (RAG / Chatbot) ──────────────────────────────── #
    try:
        def _load_fastembed():
            from backend.app.services.rag_service import get_rag_service
            svc = get_rag_service()
            if svc:
                svc._ensure_embedder()

        def _unload_fastembed():
            try:
                from backend.app.services import rag_service as _r
                _r._rag_service_instance = None
            except Exception:
                pass

        registry.register_model(
            model_id="fastembed_bge",
            name="FastEmbed — BAAI/bge-small-en",
            description="Text embedding model for RAG/Knowledge Base semantic search. 33M parameters, 384-dim embeddings. Powers the AI Chatbot knowledge retrieval.",
            category="NLP / RAG",
            ram_estimate_mb=200,
            load_fn=_load_fastembed,
            unload_fn=_unload_fastembed,
            icon="🔤",
        )
    except Exception as e:
        print(f"[ModelRegistry] Cannot register fastembed_bge: {e}")

    print(f"[ModelRegistry] ✅ {len(registry._registry)} models registered.")


# Trigger registration when this controller is imported
_register_all_models()


# ── Helper: sync actual loaded status ───────────────────────────────── #
def _sync_loaded_status():
    """Check actual in-memory state of each module and sync registry 'loaded' flag."""
    # InsightFace V1
    try:
        from backend.app.services import ml_service as ml
        registry._registry.get("insightface_v1", {})["loaded"] = ml._face_engines.get("v1") is not None
        registry._registry.get("insightface_v2", {})["loaded"] = ml._face_engines.get("v2") is not None
        registry._registry.get("emotion_onnx", {})["loaded"] = (
            ml._emotion_sessions.get("v1") is not None or ml._emotion_sessions.get("v2") is not None
        )
    except Exception:
        pass

    try:
        from backend.app.services import anti_spoof_service as sp
        registry._registry.get("antispoof_uniface_v2", {})["loaded"] = bool(sp._uniface_v2_instance)
        registry._registry.get("antispoof_uniface_v1se", {})["loaded"] = bool(sp._uniface_v1_instance)
        registry._registry.get("antispoof_native_onnx", {})["loaded"] = bool(sp._native_session)
    except Exception:
        pass

    try:
        from backend.app.services import fall_detection_service as fds
        registry._registry.get("mediapipe_pose", {})["loaded"] = fds._pose_detector is not None
    except Exception:
        pass

    try:
        from backend.app.services import hse_service as hse
        registry._registry.get("yolov8n", {})["loaded"] = "yolov8n" in hse._model_cache
    except Exception:
        pass


# ── API Endpoints ─────────────────────────────────────────────────── #

@router.get("")
def list_models(current_user=Depends(get_current_user)):
    """List all registered AI models with their current status and RAM estimates."""
    _sync_loaded_status()
    models = registry.get_all_models()

    total_ram_loaded = sum(m["ram_estimate_mb"] for m in models if m["loaded"])
    total_ram_all = sum(m["ram_estimate_mb"] for m in models)
    loaded_count = sum(1 for m in models if m["loaded"])

    return {
        "success": True,
        "models": models,
        "summary": {
            "total_models": len(models),
            "loaded_count": loaded_count,
            "unloaded_count": len(models) - loaded_count,
            "ram_used_by_models_mb": total_ram_loaded,
            "ram_total_estimate_mb": total_ram_all,
        }
    }


@router.post("/{model_id}/load")
def load_model(model_id: str, current_user=Depends(get_current_user)):
    """Load a specific model into RAM."""
    result = registry.load_model(model_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Load failed"))
    _sync_loaded_status()
    return result


@router.post("/{model_id}/unload")
def unload_model(model_id: str, current_user=Depends(get_current_user)):
    """Unload a specific model from RAM."""
    result = registry.unload_model(model_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unload failed"))
    gc.collect()
    _sync_loaded_status()
    return result


@router.post("/batch/load-all")
def load_all(current_user=Depends(get_current_user)):
    """Load all registered models into RAM."""
    results = registry.load_all_models()
    _sync_loaded_status()
    success_count = sum(1 for r in results.values() if r.get("success"))
    return {
        "success": True,
        "message": f"{success_count}/{len(results)} models loaded",
        "details": results
    }


@router.post("/batch/unload-all")
def unload_all(current_user=Depends(get_current_user)):
    """Unload all models from RAM and trigger garbage collection."""
    results = registry.unload_all_models()
    gc.collect()
    _sync_loaded_status()
    success_count = sum(1 for r in results.values() if r.get("success"))
    return {
        "success": True,
        "message": f"{success_count}/{len(results)} models unloaded",
        "details": results
    }


@router.post("/batch/unload-unused")
def unload_unused(current_user=Depends(get_current_user)):
    """Unload only models that are currently loaded (for targeted cleanup)."""
    _sync_loaded_status()
    all_models = registry.get_all_models()
    loaded_ids = [m["id"] for m in all_models if m["loaded"]]
    results = {}
    for mid in loaded_ids:
        results[mid] = registry.unload_model(mid)
    gc.collect()
    return {
        "success": True,
        "message": f"{len(loaded_ids)} loaded models unloaded",
        "details": results
    }


@router.get("/system/ram")
def get_system_ram(current_user=Depends(get_current_user)):
    """Return real-time system RAM and process memory usage."""
    if not _PSUTIL_AVAILABLE:
        return {
            "available": False,
            "error": "psutil not installed. Run: pip install psutil"
        }

    import os
    vm = psutil.virtual_memory()
    process = psutil.Process(os.getpid())
    proc_mem = process.memory_info()

    _sync_loaded_status()
    models = registry.get_all_models()
    ram_used_by_models = sum(m["ram_estimate_mb"] for m in models if m["loaded"])

    return {
        "success": True,
        "system": {
            "total_mb": round(vm.total / 1024 / 1024),
            "used_mb": round(vm.used / 1024 / 1024),
            "available_mb": round(vm.available / 1024 / 1024),
            "percent": round(vm.percent, 1),
        },
        "process": {
            "rss_mb": round(proc_mem.rss / 1024 / 1024),
            "vms_mb": round(proc_mem.vms / 1024 / 1024),
        },
        "models": {
            "loaded_count": sum(1 for m in models if m["loaded"]),
            "total_count": len(models),
            "ram_estimate_mb": ram_used_by_models,
        }
    }
