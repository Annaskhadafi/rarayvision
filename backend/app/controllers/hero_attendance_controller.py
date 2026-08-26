from fastapi import APIRouter, File, UploadFile, Form, Depends, Request, HTTPException
from sqlalchemy.orm import Session
import json
import cv2
import numpy as np
import asyncio
import os
import uuid

from backend.app.database import database as db
from backend.app.database import models as db_models
from backend.app.core.deps import get_current_user
from backend.app.services.ml_service import (
    process_register_live,
    process_recognize_live,
    get_tenant_faces,
    save_face_to_db,
    auto_harvest_face_on_match,
    load_db_face_config,
    thread_pool
)

router = APIRouter(prefix="/api/v1/hero", tags=["HERO Attendance"])

# ──────────────────────────────────────────────
# HERO FACE REGISTRATION
# Register or update an employee face embedding
# face_id = "emp-{employee_id}" by convention
# ──────────────────────────────────────────────
@router.post(
    "/register",
    summary="Register/update an employee face for HERO attendance"
)
async def hero_register_face(
    request: Request,
    employee_id: str = Form(...),
    employee_sn: str = Form(None),
    employee_name: str = Form(...),
    force: str = Form("false"),
    file: UploadFile = File(...),
    current_user: db_models.User = Depends(get_current_user),
    db_session: Session = Depends(db.get_db)
):
    """
    Register or update a face for HERO attendance.
    face_id is employee_sn if available, otherwise "emp-{employee_id}".
    Set force=true to overwrite existing registration.
    """
    face_id = employee_sn.strip() if (employee_sn and employee_sn.strip()) else (employee_id if str(employee_id).startswith("emp-") else f"emp-{employee_id}")
    force_overwrite = force.lower() in ("true", "1", "yes")
    
    try:
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            return {"status": "error", "message": "File size exceeds the 10MB limit"}
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"status": "error", "message": "Invalid or corrupted image"}

        # Check existing registration
        known_faces_db = get_tenant_faces(db_session, current_user.id)
        already_registered = any(str(item.get("id")) == str(face_id) for item in known_faces_db)
        
        if already_registered and not force_overwrite:
            return {
                "status": "already_registered",
                "message": f"Face ID '{face_id}' is already registered. Use force=true to overwrite.",
                "face_id": face_id
            }

        loop = asyncio.get_running_loop()
        # Use process_register_live (no spoof check) — spoof check is done by HERO's own server-side logic
        result = await loop.run_in_executor(
            thread_pool, lambda: process_register_live(img, check_spoof=False)
        )
        if result.get("status") != "success":
            return result

        embedding = np.array(result["embedding"], dtype=np.float32)
        final_name = employee_name.strip() if employee_name.strip() else face_id

        # Save/update image if store_images is enabled
        image_url = None
        if getattr(current_user, "store_images", False):
            filename = f"{current_user.id}_{face_id}.jpg"
            uploads_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "hero_faces"
            )
            os.makedirs(uploads_dir, exist_ok=True)
            file_path = os.path.join(uploads_dir, filename)
            cv2.imwrite(file_path, img)
            base_url = str(request.base_url).rstrip("/") if request else ""
            image_url = f"{base_url}/api/v1/uploads/hero_faces/{filename}"

        # Upsert to DB
        save_face_to_db(db_session, current_user.id, face_id, final_name, embedding, image_url)

        return {
            "status": "success",
            "message": "Face registered successfully for HERO attendance" if not already_registered else "Face updated successfully",
            "face_id": face_id,
            "employee_id": employee_id,
            "employee_name": final_name,
            "liveness_score": result.get("liveness_score"),
            "was_update": already_registered
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ──────────────────────────────────────────────
# HERO FACE RECOGNITION / ATTENDANCE CHECK
# Receives an image, identifies the face,
# returns employee_id if matched
# ──────────────────────────────────────────────
@router.post(
    "/recognize",
    summary="Recognize a face for HERO attendance — returns matched employee_id"
)
async def hero_recognize_face(
    request: Request,
    file: UploadFile = File(...),
    current_user: db_models.User = Depends(get_current_user),
    db_session: Session = Depends(db.get_db)
):
    """
    Identify who the person in the image is.
    Returns: { status, recognized, face_id, employee_id, employee_name, confidence }
    face_id format: "emp-{employee_id}"
    """
    try:
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            return {"status": "error", "message": "File size exceeds the 10MB limit"}
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"status": "error", "message": "Invalid or corrupted image"}

        loop = asyncio.get_running_loop()
        tenant_faces = get_tenant_faces(db_session, current_user.id)

        if not tenant_faces:
            return {"status": "no_faces_registered", "recognized": False, "message": "No faces registered for this tenant"}

        result = await loop.run_in_executor(
            thread_pool, process_recognize_live, img, tenant_faces, "identify"
        )

        # Parse result from process_recognize_live
        if result.get("status") == "error":
            return {"status": "error", "recognized": False, "message": result.get("message", "Recognition failed")}

        # process_recognize_live identify mode returns {"status", "match", "data": {"id", "name", "similarity"}}
        match = result.get("match", False)
        data_obj = result.get("data", {})
        
        if not match or not data_obj:
            return {
                "status": "success",
                "recognized": False,
                "confidence": float(data_obj.get("similarity", 0)) if data_obj else 0,
                "message": "Face not matched to any registered employee"
            }

        recognized_id = data_obj.get("id")
        confidence = float(data_obj.get("similarity", 0))
        name = data_obj.get("name", "")

        if not recognized_id or recognized_id == "Unknown":
            return {
                "status": "success",
                "recognized": False,
                "confidence": confidence,
                "message": "Face not matched to any registered employee"
            }

        # Auto-harvest physical image and V2 embedding in background
        base_url = str(request.base_url).rstrip("/") if request else ""
        auto_harvest_face_on_match(img, current_user.id, recognized_id, base_url)

        # Extract employee_id from face_id ("emp-123" -> "123")
        employee_id = None
        if str(recognized_id).startswith("emp-"):
            employee_id = str(recognized_id)[4:]  # Remove "emp-" prefix

        return {
            "status": "success",
            "recognized": True,
            "face_id": recognized_id,
            "employee_id": employee_id,
            "employee_name": name,
            "confidence": confidence,
        }
    except Exception as e:
        return {"status": "error", "recognized": False, "message": str(e)}


# ──────────────────────────────────────────────
# HERO FACE VERIFY (1:1 check)
# Verify a specific employee face
# ──────────────────────────────────────────────
@router.post(
    "/verify",
    summary="Verify a face against a specific employee (1:1 check)"
)
async def hero_verify_face(
    request: Request,
    employee_id: str = Form(...),
    employee_sn: str = Form(None),
    file: UploadFile = File(...),
    current_user: db_models.User = Depends(get_current_user),
    db_session: Session = Depends(db.get_db)
):
    """
    Verify if the image matches a specific employee.
    Returns confidence score and verified flag.
    """
    from backend.app.services.ml_service import process_register_logic
    import json
    
    # Generate candidate ID list to match database records (e.g., '71261', 'emp-71261', 'emp-1215', etc.)
    emp_str = str(employee_id).strip()
    candidate_ids = [
        emp_str,
        f"emp-{emp_str}",
        emp_str.replace("emp-", "")
    ]
    if employee_sn and str(employee_sn).strip():
        sn_str = str(employee_sn).strip()
        candidate_ids.extend([sn_str, f"emp-{sn_str}", sn_str.replace("emp-", "")])
    
    candidate_ids = list(dict.fromkeys(candidate_ids))
    
    try:
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            return {"status": "error", "message": "File size exceeds the 10MB limit"}
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"status": "error", "message": "Invalid or corrupted image"}

        # Get stored embedding for this employee across all candidate aliases
        stored_face = db_session.query(db_models.Face).filter(
            db_models.Face.user_id == current_user.id,
            db_models.Face.face_id.in_(candidate_ids)
        ).first()

        if not stored_face:
            return {
                "status": "not_registered",
                "verified": False,
                "message": f"Employee {employee_id} has no registered face"
            }

        # Extract embedding from live image
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            thread_pool, lambda: process_register_logic(img, check_spoof=False)
        )
        if result.get("status") != "success":
            return {"status": "error", "verified": False, "message": result.get("message", "Face not detected")}

        live_embedding = np.array(result["embedding"], dtype=np.float32)
        stored_embedding = np.array(json.loads(stored_face.embedding), dtype=np.float32)

        # Cosine similarity
        dot = float(np.dot(live_embedding, stored_embedding))
        norm_live = float(np.linalg.norm(live_embedding))
        norm_stored = float(np.linalg.norm(stored_embedding))
        similarity = dot / (norm_live * norm_stored) if norm_live > 0 and norm_stored > 0 else 0.0

        cfg = load_db_face_config(db_session)
        THRESHOLD = cfg["threshold"]
        verified = similarity >= THRESHOLD and similarity < 1.0  # < 1.0 to reject replay

        if verified:
            base_url = str(request.base_url).rstrip("/") if request else ""
            auto_harvest_face_on_match(img, current_user.id, stored_face.face_id, base_url)

        return {
            "status": "success",
            "verified": verified,
            "employee_id": employee_id,
            "face_id": stored_face.face_id,
            "confidence": round(similarity, 4),
            "threshold": THRESHOLD,
        }
    except Exception as e:
        return {"status": "error", "verified": False, "message": str(e)}


# ──────────────────────────────────────────────
# HERO FACE STATUS CHECK
# Check if an employee has a registered face
# ──────────────────────────────────────────────
@router.get(
    "/status/{employee_id}",
    summary="Check HERO employee face registration status"
)
async def hero_face_status(
    employee_id: str,
    current_user: db_models.User = Depends(get_current_user),
    db_session: Session = Depends(db.get_db)
):
    emp_str = str(employee_id).strip()
    candidate_ids = list(dict.fromkeys([
        emp_str,
        f"emp-{emp_str}",
        emp_str.replace("emp-", "")
    ]))

    face = db_session.query(db_models.Face).filter(
        db_models.Face.user_id == current_user.id,
        db_models.Face.face_id.in_(candidate_ids)
    ).first()

    if not face:
        return {"status": "success", "registered": False, "employee_id": employee_id}

    return {
        "status": "success",
        "registered": True,
        "employee_id": employee_id,
        "face_id": face.face_id,
        "registered_at": face.created_at.isoformat() if face.created_at else None
    }


# ──────────────────────────────────────────────
# HERO FACE DELETE
# ──────────────────────────────────────────────
@router.delete(
    "/unregister/{employee_id}",
    summary="Delete HERO employee face registration"
)
async def hero_unregister_face(
    employee_id: str,
    current_user: db_models.User = Depends(get_current_user),
    db_session: Session = Depends(db.get_db)
):
    from backend.app.services.ml_service import delete_face_from_db
    emp_str = str(employee_id).strip()
    candidate_ids = list(dict.fromkeys([
        emp_str,
        f"emp-{emp_str}",
        emp_str.replace("emp-", "")
    ]))
    
    try:
        for cid in candidate_ids:
            delete_face_from_db(db_session, current_user.id, cid)
        return {"status": "success", "message": f"Face for employee {employee_id} deleted"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
