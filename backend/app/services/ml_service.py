import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import cv2
cv2.setNumThreads(1)
try:
    import torch
    torch.set_num_threads(1)
except Exception:
    pass

import numpy as np
import insightface
from insightface.app import FaceAnalysis
import onnxruntime as ort
import json
import base64
import time
from typing import Optional, Dict, Any, List
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from backend.app.database import database as db
from backend.app.database import models as db_models
from backend.app.core.config import (
    ANTI_SPOOF_MODEL_PATH,
    ANTI_SPOOF_INT8_MODEL_PATH,
    EMOTION_MODEL_PATH,
    EMOTION_INT8_MODEL_PATH,
    DEFAULT_FACE_ENGINE_MODE
)
import uuid
import requests

# Configure ONNX Runtime Session Options to limit CPU threads per worker
ort_session_options = ort.SessionOptions()
ort_session_options.intra_op_num_threads = 1
ort_session_options.inter_op_num_threads = 1
ort_session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

# --- CHECK CUDA SUPPORT ---
available_providers = ['CPUExecutionProvider']
if 'CUDAExecutionProvider' in ort.get_available_providers():
    available_providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
    print("[+] CUDA GPU Detected! Running ML models on GPU.")
else:
    print("[i] No GPU detected. Running ML models on CPU (1 thread per worker).")

# --- DUAL-ENGINE ARCHITECTURE STATE ---
_active_engine_mode = DEFAULT_FACE_ENGINE_MODE if DEFAULT_FACE_ENGINE_MODE in ["v1", "v2"] else "v1"
_face_engines: Dict[str, Any] = {"v1": None, "v2": None}
_spoof_sessions: Dict[str, Any] = {"v1": None, "v2": None}
_emotion_sessions: Dict[str, Any] = {"v1": None, "v2": None}

def set_global_engine_mode(mode: str) -> str:
    global _active_engine_mode
    if mode in ["v1", "v2"]:
        _active_engine_mode = mode
        print(f"[Engine] Global Face Engine switched to: {_active_engine_mode.upper()}")
        # Pre-warm target engine
        get_face_app(_active_engine_mode)
        get_spoof_session(_active_engine_mode)
    return _active_engine_mode

def get_global_engine_mode() -> str:
    return _active_engine_mode

def get_face_app(mode: Optional[str] = None):
    target_mode = mode if mode in ["v1", "v2"] else _active_engine_mode
    if _face_engines[target_mode] is None:
        model_name = 'buffalo_l' if target_mode == 'v1' else 'buffalo_s'
        print(f"[*] Initializing InsightFace Engine {target_mode.upper()} ({model_name})...")
        try:
            app = FaceAnalysis(name=model_name, providers=available_providers)
            app.prepare(ctx_id=0, det_size=(640, 640))
            _face_engines[target_mode] = app
            print(f"[+] InsightFace Engine {target_mode.upper()} ({model_name}) loaded successfully!")
        except Exception as e:
            print(f"[-] Failed to load InsightFace Engine {target_mode.upper()} ({model_name}): {e}")
            if target_mode != "v1" and _face_engines.get("v1") is not None:
                return _face_engines["v1"]
    return _face_engines[target_mode]

def get_spoof_session(mode: Optional[str] = None):
    target_mode = mode if mode in ["v1", "v2"] else _active_engine_mode
    if _spoof_sessions[target_mode] is None:
        path = ANTI_SPOOF_MODEL_PATH if target_mode == "v1" else ANTI_SPOOF_INT8_MODEL_PATH
        if not os.path.exists(path) and target_mode == "v2":
            path = ANTI_SPOOF_MODEL_PATH
        if os.path.exists(path):
            try:
                _spoof_sessions[target_mode] = ort.InferenceSession(path, sess_options=ort_session_options, providers=available_providers)
                print(f"[+] Anti-Spoofing session {target_mode.upper()} loaded from {os.path.basename(path)}!")
            except Exception as e:
                print(f"[-] Error loading Anti-Spoofing session {target_mode.upper()}: {e}")
    return _spoof_sessions[target_mode]

def get_emotion_session(mode: Optional[str] = None):
    target_mode = mode if mode in ["v1", "v2"] else _active_engine_mode
    if _emotion_sessions[target_mode] is None:
        path = EMOTION_MODEL_PATH if target_mode == "v1" else EMOTION_INT8_MODEL_PATH
        if not os.path.exists(path) and target_mode == "v2":
            path = EMOTION_MODEL_PATH
        if os.path.exists(path):
            try:
                _emotion_sessions[target_mode] = ort.InferenceSession(path, sess_options=ort_session_options, providers=available_providers)
                print(f"[+] Emotion session {target_mode.upper()} loaded from {os.path.basename(path)}!")
            except Exception as e:
                print(f"[-] Error loading Emotion session {target_mode.upper()}: {e}")
    return _emotion_sessions[target_mode]

# Preload the default active engine on startup
print(f"[*] Preloading Default Face Engine ({_active_engine_mode.upper()})...")
try:
    get_face_app(_active_engine_mode)
    get_spoof_session(_active_engine_mode)
except Exception as e:
    print(f"[-] Preload warning: {e}")

# Backward-compatibility alias
face_app = get_face_app("v1")
spoof_session = get_spoof_session("v1")
emotion_session = get_emotion_session("v1")

# Thread Pool untuk memproses gambar di background (diatur ke 2 worker untuk mencegah CPU 100%)
thread_pool = ThreadPoolExecutor(max_workers=2)
client_buffers = {}

def _optimize_input_image(img, max_dim=1280):
    """Downscales oversized camera/upload frames before feeding to deep learning models."""
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        scale = max_dim / float(max(h, w))
        new_w, new_h = int(w * scale), int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return img

# --- DATABASE WAJAH ---
def get_tenant_faces(db_session, user_id):
    faces = db_session.query(db_models.Face).filter(db_models.Face.user_id == user_id).all()
    result = []
    for row in faces:
        try:
            emb_list = json.loads(row.embedding)
            result.append({
                "id": row.face_id,
                "name": row.name,
                "embedding": np.array(emb_list, dtype=np.float32)
            })
        except Exception as e:
            print(f"Error load face {row.face_id}: {e}")
    return result

def save_face_to_db(db_session, user_id, face_id, name, embedding, image_url=None):
    emb_json = json.dumps(np.array(embedding, dtype=np.float32).tolist())
    face = db_session.query(db_models.Face).filter(db_models.Face.user_id == user_id, db_models.Face.face_id == face_id).first()
    if face:
        face.name = name
        face.embedding = emb_json
        if image_url:
            face.image_url = image_url
        face.created_at = datetime.utcnow()
    else:
        face = db_models.Face(user_id=user_id, face_id=face_id, name=name, embedding=emb_json, image_url=image_url)
        db_session.add(face)
    db_session.commit()

def delete_face_from_db(db_session, user_id, face_id):
    face = db_session.query(db_models.Face).filter(db_models.Face.user_id == user_id, db_models.Face.face_id == face_id).first()
    if face:
        image_url = face.image_url
        db_session.delete(face)
        db_session.commit()
        
        # Hapus file fisik foto jika ada
        if image_url:
            import os
            filename = os.path.basename(image_url)
            # File mungkin disimpan di dua lokasi berbeda berdasarkan controller
            path1 = os.path.join(os.path.dirname(os.path.dirname(__file__)), "controllers", "uploads", "faces", filename)
            path2 = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "faces", filename)
            
            for p in [path1, path2]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception as e:
                        print(f"Error deleting file {p}: {e}")
                        
        return True
    return False

# --- AUTHENTICATION DEPENDENCIES ---
def _get_new_box(src_w, src_h, bbox, scale):
    x = bbox[0]
    y = bbox[1]
    box_w = bbox[2] - bbox[0]
    box_h = bbox[3] - bbox[1]

    scale = min((src_h-1)/box_h, min((src_w-1)/box_w, scale))

    new_width = box_w * scale
    new_height = box_h * scale
    center_x, center_y = box_w/2+x, box_h/2+y

    left_top_x = center_x-new_width/2
    left_top_y = center_y-new_height/2
    right_bottom_x = center_x+new_width/2
    right_bottom_y = center_y+new_height/2

    if left_top_x < 0:
        right_bottom_x -= left_top_x
        left_top_x = 0

    if left_top_y < 0:
        right_bottom_y -= left_top_y
        left_top_y = 0

    if right_bottom_x > src_w-1:
        left_top_x -= right_bottom_x-src_w+1
        right_bottom_x = src_w-1

    if right_bottom_y > src_h-1:
        left_top_y -= right_bottom_y-src_h+1
        right_bottom_y = src_h-1

    return int(left_top_x), int(left_top_y), int(right_bottom_x), int(right_bottom_y)

def crop_face_for_spoof(img, bbox, kps=None, scale=2.7):
    """Crop face area using official minivision logic"""
    src_h, src_w, _ = np.shape(img)
    left_top_x, left_top_y, right_bottom_x, right_bottom_y = _get_new_box(src_w, src_h, bbox, scale)

    cropped = img[left_top_y: right_bottom_y+1, left_top_x: right_bottom_x+1]

    # Lakukan rotasi alignment pada hasil crop jika ada KPS (wajah miring)
    if kps is not None and len(kps) >= 2:
        left_eye = kps[0]
        right_eye = kps[1]
        dy = right_eye[1] - left_eye[1]
        dx = right_eye[0] - left_eye[0]
        angle = np.degrees(np.arctan2(dy, dx))
        
        # Hanya rotasi jika kemiringan lebih dari 5 derajat
        if abs(angle) > 5.0:
            crop_center = (cropped.shape[1] // 2, cropped.shape[0] // 2)
            M = cv2.getRotationMatrix2D(crop_center, angle, 1.0)
            cropped = cv2.warpAffine(cropped, M, (cropped.shape[1], cropped.shape[0]), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=[0, 0, 0])
            
    return cropped

def check_liveness(img, bbox, kps=None, engine_mode: Optional[str] = None):
    """Main liveness verification function — model: MiniFASNetV2 (80x80, 3-class)"""
    session = get_spoof_session(engine_mode)
    if session:
        try:
            # Scale 2.7 adalah standar MiniFASNet
            face_roi = crop_face_for_spoof(img, bbox, kps=kps, scale=2.7)
            if face_roi.size == 0 or face_roi.shape[0] < 10 or face_roi.shape[1] < 10:
                return 0.0, False
            # Resize ke 80x80 sesuai input model baru
            face_roi = cv2.resize(face_roi, (80, 80))

            # MiniFASNet menggunakan RAW BGR, tanpa divide by 255, tanpa normalization
            face_roi_bgr = face_roi.astype(np.float32)

            # HWC -> CHW -> NCHW
            face_roi_bgr = np.expand_dims(face_roi_bgr.transpose(2, 0, 1), axis=0)

            input_name = session.get_inputs()[0].name
            outputs = session.run(None, {input_name: face_roi_bgr})

            prediction = outputs[0]
            # Softmax
            exp_pred = np.exp(prediction - np.max(prediction, axis=1, keepdims=True))
            probs = exp_pred / np.sum(exp_pred, axis=1, keepdims=True)
            # index 1 = Real, index 0/2 = Spoof
            real_score = float(probs[0][1])
            is_real = real_score > 0.55
            return real_score, is_real
        except Exception as e:
            print(f"Spoof Check Error: {e}")
            return 0.0, False
    else:
        # Fallback: multi-metric analysis tanpa model
        try:
            x1, y1, x2, y2 = bbox.astype(int)
            face_roi = img[y1:y2, x1:x2]
            if face_roi.size == 0: return 0.0, False
            
            gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            
            # Laplacian sharpness
            lap_score = cv2.Laplacian(gray, cv2.CV_64F).var()
            
            # Color diversity — foto biasanya lebih flat warnanya
            hsv = cv2.cvtColor(face_roi, cv2.COLOR_BGR2HSV)
            sat_std = np.std(hsv[:,:,1].astype(np.float32))
            
            # Gabungkan
            norm_lap = min(lap_score / 150.0, 1.0)
            norm_sat = min(sat_std / 40.0, 1.0)
            combined = (norm_lap * 0.6 + norm_sat * 0.4)
            
            is_real = combined > 0.35
            return float(combined), bool(is_real)
        except:
            return 0.0, False

def compute_similarity(embed1, embed2):
    return np.dot(embed1, embed2) / (np.linalg.norm(embed1) * np.linalg.norm(embed2))

# ================= LOGIC FUNCTIONS (THREAD SAFE) =================

def process_image_sync(img, engine_mode: Optional[str] = None):
    """Logic untuk Socket.IO /analyze-face (General Analysis)"""
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    
    # --- VALIDASI JUMLAH WAJAH ---
    if len(faces) > 1:
        return [] 
        
    results = []
    current_mode = engine_mode or _active_engine_mode
    
    for face in faces:
        liveness_score, is_real = check_liveness(img, face.bbox, kps=face.kps, engine_mode=current_mode)
        gender = "Laki-laki" if face.gender == 1 else "Perempuan"
        
        raw_age = int(getattr(face, "age", 0)) if getattr(face, "age", 0) is not None and getattr(face, "age", 0) != -1 else 0
        if raw_age > 35: calibrated_age = raw_age - 9
        elif raw_age > 25: calibrated_age = raw_age - 6
        elif raw_age > 15: calibrated_age = raw_age - 3
        else: calibrated_age = raw_age
        
        results.append({
            "bbox": face.bbox.astype(int).tolist(),
            "gender": gender,
            "age": max(1, calibrated_age),
            "embedding": face.embedding.tolist(),
            "landmarks": face.kps.astype(int).tolist(),
            "liveness": {
                "score": liveness_score,
                "is_real": is_real,
                "method": "MiniFASNetV2" if get_spoof_session(current_mode) else "Laplacian"
            }
        })
    return results

def process_liveness_only(img, engine_mode: Optional[str] = None):
    """Logic untuk Endpoint /check-liveness"""
    start_t = time.perf_counter()
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    
    if len(faces) == 0:
        return {"status": "error", "message": "Face not detected"}
    
    # --- VALIDASI JUMLAH WAJAH ---
    if len(faces) > 1:
        return {"status": "error", "message": "Multiple faces detected. Please use a single face image."}
    
    # Process only one face (faces[0])
    face = faces[0]
    current_mode = engine_mode or _active_engine_mode
    score, is_real = check_liveness(img, face.bbox, kps=face.kps, engine_mode=current_mode)
    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
    
    return {
        "status": "success",
        "is_real": is_real,
        "score": score,
        "engine_mode": current_mode,
        "latency_ms": latency_ms
    }

def process_register_live(img, check_spoof=True, engine_mode: Optional[str] = None):
    """Register dari live camera"""
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    
    if len(faces) == 0:
        return {"status": "error", "message": "Face not detected"}

    if len(faces) > 1:
        return {"status": "error", "message": "Multiple faces detected. Please use a single face photo."}
    
    face = faces[0]
    score = 1.0
    current_mode = engine_mode or _active_engine_mode
    
    if check_spoof:
        score, is_real = check_liveness(img, face.bbox, kps=face.kps, engine_mode=current_mode)
        if not is_real:
            return {
                "status": "error",
                "message": f"Liveness check failed (score: {score:.2f}). Pastikan wajah asli di depan kamera dengan pencahayaan cukup."
            }

    return {
        "status": "success",
        "embedding": face.embedding.tolist(),
        "liveness_score": score,
        "engine_mode": current_mode
    }

def process_register_logic(img, check_spoof=True, engine_mode: Optional[str] = None):
    """Logic untuk Endpoint /extract-face (Register)"""
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    
    if len(faces) == 0:
        return {"status": "error", "message": "Face not detected in the image"}

    if len(faces) > 1:
        return {"status": "error", "message": "Multiple faces detected. Please upload an image with a single face."}
    
    face = faces[0]
    score = 1.0
    current_mode = engine_mode or _active_engine_mode

    # Liveness check opsional
    if check_spoof:
        score, is_real = check_liveness(img, face.bbox, kps=face.kps, engine_mode=current_mode)
        if not is_real:
            return {"status": "error", "message": "Spoof face or screen detected"}

    return {
        "status": "success",
        "embedding": face.embedding.tolist(),
        "liveness_score": score,
        "engine_mode": current_mode
    }

def process_compare_logic(img, user_id, tenant_faces, engine_mode: Optional[str] = None):
    """Logic for /compare-face endpoint (1:1 verification)"""
    start_t = time.perf_counter()
    if not user_id:
        user_id = "face_" + uuid.uuid4().hex[:8]
    known_faces_db = tenant_faces
    
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    
    if len(faces) == 0:
        return {"status": "error", "message": "Face not detected"}

    # --- VALIDASI JUMLAH WAJAH ---
    if len(faces) > 1:
        return {"status": "error", "message": "Multiple faces detected. Please ensure only one face is visible."}
    
    target_face = faces[0]

    # 1. Search in RAM
    user_data = next((u for u in known_faces_db if str(u["id"]) == str(user_id)), None)
    target_embedding_db = None

    if user_data:
        target_embedding_db = user_data['embedding']

    if target_embedding_db is None:
        return {"status": "error", "message": "User face is not registered"}

    # 3. Bandingkan
    similarity = compute_similarity(target_face.embedding, target_embedding_db)
    THRESHOLD = 0.45 
    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
    current_mode = engine_mode or _active_engine_mode
    
    if similarity > THRESHOLD:
        return {
            "status": "success",
            "match": True,
            "similarity": float(similarity),
            "message": "Face matched",
            "engine_mode": current_mode,
            "latency_ms": latency_ms
        }
    else:
        return {
            "status": "success",
            "match": False,
            "similarity": float(similarity),
            "message": "Face did not match",
            "engine_mode": current_mode,
            "latency_ms": latency_ms
        }

def process_recognize_live(img, tenant_faces, mode="identify", engine_mode: Optional[str] = None):
    """Logic for /recognize-live endpoint supporting multi-mode (identify, analyze, liveness)"""
    start_t = time.perf_counter()
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    if len(faces) == 0:
        return {"status": "error", "message": "Face not detected"}

    if len(faces) > 1:
        return {"status": "error", "message": "Multiple faces detected"}

    target_face = faces[0]
    bbox = target_face.bbox.astype(int).tolist()
    landmarks = target_face.kps.astype(int).tolist() if hasattr(target_face, "kps") and target_face.kps is not None else []
    current_mode = engine_mode or _active_engine_mode
    
    base_data = {"bbox": bbox, "landmarks": landmarks}

    if mode == "analyze":
        gender_val = getattr(target_face, "gender", None)
        gender = "Male" if gender_val == 1 else "Female" if gender_val == 0 else "Unknown"
        
        raw_age = int(getattr(target_face, "age", 0)) if getattr(target_face, "age", 0) is not None and getattr(target_face, "age", 0) != -1 else 0
        if raw_age > 35: calibrated_age = raw_age - 9
        elif raw_age > 25: calibrated_age = raw_age - 6
        elif raw_age > 15: calibrated_age = raw_age - 3
        else: calibrated_age = raw_age

        return {
            "status": "success",
            "mode": mode,
            "engine_mode": current_mode,
            "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
            "data": {
                **base_data,
                "age": max(1, calibrated_age),
                "gender": gender
            }
        }
        
    if mode == "liveness":
        real_score, is_real = check_liveness(img, target_face.bbox, kps=target_face.kps, engine_mode=current_mode)
        return {
            "status": "success",
            "mode": mode,
            "engine_mode": current_mode,
            "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
            "data": {
                **base_data,
                "liveness_score": float(real_score),
                "is_real": bool(is_real)
            }
        }

    if mode == "liveness_identify":
        real_score, is_real = check_liveness(img, target_face.bbox, kps=target_face.kps, engine_mode=current_mode)
        if not is_real:
            return {
                "status": "success",
                "mode": mode,
                "engine_mode": current_mode,
                "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
                "data": {
                    **base_data,
                    "liveness_score": float(real_score),
                    "is_real": bool(is_real),
                    "match": False,
                    "id": None,
                    "name": "Spoof Detected"
                }
            }
        
        target_embedding = target_face.embedding
        best_score = 0
        best_match = None

        for user in tenant_faces:
            sim = compute_similarity(target_embedding, user['embedding'])
            if sim > best_score:
                best_score = sim
                best_match = user

        if best_score > 0.50:
            return {
                "status": "success", "match": True, "mode": mode,
                "engine_mode": current_mode,
                "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
                "data": {
                    **base_data,
                    "liveness_score": float(real_score),
                    "is_real": bool(is_real),
                    "id": best_match['id'], 
                    "name": best_match['name'], 
                    "similarity": float(best_score)
                }
            }
        else:
            return {
                "status": "success", "match": False, "mode": mode,
                "engine_mode": current_mode,
                "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
                "data": {
                    **base_data,
                    "liveness_score": float(real_score),
                    "is_real": bool(is_real),
                    "id": None, 
                    "name": "Unknown", 
                    "similarity": float(best_score)
                }
            }

    if mode == "emotion":
        emotion_result = "Unknown"
        emotion_score = 0.0
        active_emotion_sess = get_emotion_session(current_mode)
        if active_emotion_sess:
            x1, y1, x2, y2 = target_face.bbox.astype(int)
            raw_face_roi = img[y1:y2, x1:x2]
            if raw_face_roi.size > 0:
                gray_face = cv2.cvtColor(raw_face_roi, cv2.COLOR_BGR2GRAY)
                resized_face = cv2.resize(gray_face, (64, 64))
                input_data = np.expand_dims(np.expand_dims(resized_face, axis=0), axis=0).astype(np.float32)
                
                try:
                    outputs = active_emotion_sess.run(None, {active_emotion_sess.get_inputs()[0].name: input_data})
                    logits = outputs[0][0]
                    exp_pred = np.exp(logits - np.max(logits))
                    probs = exp_pred / np.sum(exp_pred)
                    
                    emotions = ['Neutral', 'Happy', 'Surprise', 'Sad', 'Angry', 'Disgust', 'Fear', 'Contempt']
                    best_idx = np.argmax(probs)
                    emotion_result = emotions[best_idx]
                    emotion_score = float(probs[best_idx])
                except Exception as e:
                    print(f"Error emotion inference: {e}")

        return {
            "status": "success",
            "mode": mode,
            "engine_mode": current_mode,
            "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
            "data": {
                **base_data,
                "emotion": emotion_result,
                "emotion_score": emotion_score
            }
        }

    if mode == "attributes":
        glasses_detected = False
        mask_detected = False
        
        x1, y1, x2, y2 = target_face.bbox.astype(int)
        raw_face_roi = img[max(0, y1):y2, max(0, x1):x2]
        
        if raw_face_roi.size > 0:
            gray_face = cv2.cvtColor(raw_face_roi, cv2.COLOR_BGR2GRAY)
            
            # Deteksi kacamata menggunakan edge density pada area mata
            h, w = gray_face.shape
            eyes_roi = gray_face[int(h*0.2):int(h*0.55), :]
            if eyes_roi.size > 0:
                blurred = cv2.GaussianBlur(eyes_roi, (5, 5), 0)
                edges = cv2.Canny(blurred, 50, 150)
                density = np.sum(edges > 0) / edges.size
                glasses_detected = bool(density > 0.05)
            
            smile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_smile.xml')
            lower_face = gray_face[int(h/2):h, 0:w]
            smiles = smile_cascade.detectMultiScale(lower_face, scaleFactor=1.2, minNeighbors=3)
            mask_detected = bool(len(smiles) == 0)

        return {
            "status": "success",
            "mode": mode,
            "engine_mode": current_mode,
            "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
            "data": {
                **base_data,
                "glasses": glasses_detected,
                "mask": mask_detected
            }
        }

    # Default to identify mode
    target_embedding = target_face.embedding
    best_score = 0
    best_match = None

    for user in tenant_faces:
        sim = compute_similarity(target_embedding, user['embedding'])
        if sim > best_score:
            best_score = sim
            best_match = user

    if best_score > 0.50:
        return {
            "status": "success", "match": True, "mode": mode,
            "engine_mode": current_mode,
            "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
            "data": {
                "id": best_match['id'], 
                "name": best_match['name'], 
                "similarity": float(best_score),
                **base_data
            }
        }
    else:
        return {
            "status": "success", 
            "match": False, 
            "mode": mode,
            "engine_mode": current_mode,
            "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
            "message": "Face not recognized",
            "data": base_data
        }

def process_recognize_logic(img, tenant_faces, engine_mode: Optional[str] = None):
    """Logic for /recognize endpoint (1:N identification)"""
    start_t = time.perf_counter()
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    if len(faces) == 0:
        return {"status": "error", "message": "Face not detected"}
    
    # --- VALIDASI JUMLAH WAJAH ---
    if len(faces) > 1:
        return {"status": "error", "message": "Multiple faces detected."}
    
    target_face = faces[0]
    target_embedding = target_face.embedding
    best_score = 0
    best_match = None

    for user in tenant_faces:
        sim = compute_similarity(target_embedding, user['embedding'])
        if sim > best_score:
            best_score = sim
            best_match = user
            
    current_mode = engine_mode or _active_engine_mode
    latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
    if best_score > 0.50:
        return {
            "status": "success", "match": True,
            "data": { "id": best_match['id'], "name": best_match['name'], "similarity": float(best_score) },
            "engine_mode": current_mode,
            "latency_ms": latency_ms
        }
    else:
        return { 
            "status": "success", "match": False, "message": "Face not recognized",
            "engine_mode": current_mode,
            "latency_ms": latency_ms
        }

def process_recognize_multi(img, tenant_faces, engine_mode: Optional[str] = None):
    """Logic for /recognize-multi and /recognize-live-multi endpoint (multi-face identification)"""
    start_t = time.perf_counter()
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    if len(faces) == 0:
        return {"status": "error", "message": "Face not detected"}
    
    results = []

    for target_face in faces:
        bbox = target_face.bbox.astype(int).tolist()
        landmarks = target_face.kps.astype(int).tolist() if hasattr(target_face, "kps") and target_face.kps is not None else []
        target_embedding = target_face.embedding
        
        base_data = {"bbox": bbox, "landmarks": landmarks}
        
        best_score = 0
        best_match = None

        for user in tenant_faces:
            sim = compute_similarity(target_embedding, user['embedding'])
            if sim > best_score:
                best_score = sim
                best_match = user
                
        if best_score > 0.50:
            results.append({
                "match": True,
                "data": {
                    "id": best_match['id'], 
                    "name": best_match['name'], 
                    "similarity": float(best_score),
                    **base_data
                }
            })
        else:
            results.append({
                "match": False,
                "message": "Face not recognized",
                "data": base_data
            })

    current_mode = engine_mode or _active_engine_mode
    return {
        "status": "success",
        "mode": "identify_multi",
        "engine_mode": current_mode,
        "latency_ms": round((time.perf_counter() - start_t) * 1000, 2),
        "faces": results
    }

def process_global_face_login(img, db_session, engine_mode: Optional[str] = None):
    """Logic for global face login"""
    active_app = get_face_app(engine_mode)
    faces = active_app.get(img) if active_app else []
    if len(faces) == 0:
        return {"status": "error", "message": "Face not detected"}
    
    if len(faces) > 1:
        return {"status": "error", "message": "Multiple faces detected. Please ensure only one face is visible."}
    
    target_face = faces[0]
    target_embedding = target_face.embedding
    current_mode = engine_mode or _active_engine_mode
    
    # --- CHECK LIVENESS ---
    liveness_score, is_real = check_liveness(img, target_face.bbox, kps=target_face.kps, engine_mode=current_mode)
    if not is_real:
        return {"status": "error", "message": f"Wajah palsu terdeteksi! (Spoof Score: {100 - (liveness_score*100):.1f}%)"}
    
    all_faces = db_session.query(db_models.Face).filter(db_models.Face.name == 'Face Login Profile').all()
    best_score = 0
    best_match = None
    
    for row in all_faces:
        try:
            emb_list = json.loads(row.embedding)
            db_embedding = np.array(emb_list, dtype=np.float32)
            sim = compute_similarity(target_embedding, db_embedding)
            if sim > best_score:
                best_score = sim
                best_match = row
        except Exception as e:
            continue
            
    if best_score > 0.50 and best_match:
        user = db_session.query(db_models.User).filter(db_models.User.id == best_match.user_id).first()
        if user:
            return {
                "status": "success",
                "match": True,
                "user_id": user.id,
                "email": user.email,
                "similarity": float(best_score),
                "engine_mode": current_mode
            }
        
    return { "status": "success", "match": False, "message": "Face not recognized or user not found" }

def benchmark_engines_comparison(img):
    """Runs single image through both V1 (Standard) and V2 (CPU Turbo) engines and compares latency & accuracy."""
    img = _optimize_input_image(img)
    if img is None:
        return {"status": "error", "message": "Invalid image"}

    # --- BENCHMARK V1 (Standard buffalo_l + FP32) ---
    t0 = time.perf_counter()
    app_v1 = get_face_app("v1")
    faces_v1 = app_v1.get(img) if app_v1 else []
    t_det_v1 = (time.perf_counter() - t0) * 1000

    v1_face_data = None
    v1_emb = None
    if faces_v1 and len(faces_v1) > 0:
        face1 = faces_v1[0]
        v1_emb = face1.embedding
        t_live_0 = time.perf_counter()
        score_v1, is_real_v1 = check_liveness(img, face1.bbox, kps=face1.kps, engine_mode="v1")
        t_live_v1 = (time.perf_counter() - t_live_0) * 1000
        v1_face_data = {
            "bbox": face1.bbox.astype(int).tolist(),
            "landmarks": face1.kps.astype(int).tolist() if hasattr(face1, "kps") and face1.kps is not None else [],
            "liveness_score": round(score_v1, 4),
            "is_real": is_real_v1,
            "det_latency_ms": round(t_det_v1, 2),
            "liveness_latency_ms": round(t_live_v1, 2),
            "total_latency_ms": round(t_det_v1 + t_live_v1, 2)
        }
    else:
        v1_face_data = {
            "detected": False,
            "total_latency_ms": round(t_det_v1, 2)
        }

    # --- BENCHMARK V2 (CPU Turbo buffalo_s + INT8) ---
    t0_v2 = time.perf_counter()
    app_v2 = get_face_app("v2")
    faces_v2 = app_v2.get(img) if app_v2 else []
    t_det_v2 = (time.perf_counter() - t0_v2) * 1000

    v2_face_data = None
    v2_emb = None
    if faces_v2 and len(faces_v2) > 0:
        face2 = faces_v2[0]
        v2_emb = face2.embedding
        t_live_0 = time.perf_counter()
        score_v2, is_real_v2 = check_liveness(img, face2.bbox, kps=face2.kps, engine_mode="v2")
        t_live_v2 = (time.perf_counter() - t_live_0) * 1000
        v2_face_data = {
            "bbox": face2.bbox.astype(int).tolist(),
            "landmarks": face2.kps.astype(int).tolist() if hasattr(face2, "kps") and face2.kps is not None else [],
            "liveness_score": round(score_v2, 4),
            "is_real": is_real_v2,
            "det_latency_ms": round(t_det_v2, 2),
            "liveness_latency_ms": round(t_live_v2, 2),
            "total_latency_ms": round(t_det_v2 + t_live_v2, 2)
        }
    else:
        v2_face_data = {
            "detected": False,
            "total_latency_ms": round(t_det_v2, 2)
        }

    # Compute similarity between V1 and V2 embeddings if both detected
    embedding_agreement = 0.0
    if v1_emb is not None and v2_emb is not None:
        try:
            embedding_agreement = round(float(compute_similarity(v1_emb, v2_emb)), 4)
        except Exception:
            embedding_agreement = 0.0

    speedup_ratio = 1.0
    v1_tot = v1_face_data.get("total_latency_ms", 0)
    v2_tot = v2_face_data.get("total_latency_ms", 0)
    if v1_tot > 0 and v2_tot > 0:
        speedup_ratio = round(v1_tot / max(v2_tot, 0.1), 2)

    latency_reduction = 0.0
    if v1_tot > 0 and v2_tot > 0:
        latency_reduction = round((1 - (v2_tot / max(v1_tot, 0.1))) * 100, 1)

    return {
        "status": "success",
        "timestamp": datetime.utcnow().isoformat(),
        "v1_standard": {
            "name": "Engine V1 (Standard - Buffalo_L & FP32)",
            "model_detection": "SCRFD-10G (ResNet50)",
            "model_recognition": "ArcFace ResNet50 (FP32)",
            "model_antispoof": "MiniFASNetV2 (FP32)",
            "data": v1_face_data
        },
        "v2_cpu_turbo": {
            "name": "Engine V2 (CPU Turbo - Buffalo_S & INT8)",
            "model_detection": "SCRFD-500M / 2.5G",
            "model_recognition": "MobileFaceNet / ResNet (INT8)",
            "model_antispoof": "MiniFASNetV2 (INT8 Quantized)",
            "data": v2_face_data
        },
        "comparison": {
            "embedding_similarity": embedding_agreement,
            "speedup_ratio": f"{speedup_ratio}x faster on CPU",
            "latency_reduction_percent": latency_reduction
        }
    }


# ================= REST API ENDPOINTS =================

