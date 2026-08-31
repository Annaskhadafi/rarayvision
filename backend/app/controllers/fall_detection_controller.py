import os
import io
import json
import uuid
import base64
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body, Query
from sqlalchemy.orm import Session

from backend.app.database.database import get_db
from backend.app.database.models import HSEIncident, User
from backend.app.core.deps import api_key_header
from backend.app.services.fall_detection_service import (
    process_fall_frame,
    process_fall_video
)

router = APIRouter(prefix="/api/v1/hse/fall-detection", tags=["Fall Detection AI"])

def _get_optional_user(
    api_key: Optional[str] = Depends(api_key_header),
    db: Session = Depends(get_db)
) -> Optional[User]:
    if not api_key:
        return None
    try:
        from backend.app.core.deps import get_current_user
        return get_current_user(api_key, db)
    except Exception:
        return None

def _save_base64_image_to_uploads(b64_str: str) -> Optional[str]:
    """Saves a base64 image string to uploads directory and returns its relative URL."""
    try:
        if "," in b64_str:
            b64_str = b64_str.split(",")[1]
        img_data = base64.b64decode(b64_str)
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        uploads_dir = os.path.abspath(os.path.join(cur_dir, "..", "..", "uploads"))
        os.makedirs(uploads_dir, exist_ok=True)
        filename = f"fall_snapshot_{uuid.uuid4().hex[:10]}.jpg"
        filepath = os.path.join(uploads_dir, filename)
        with open(filepath, "wb") as f:
            f.write(img_data)
        return f"/api/v1/uploads/{filename}"
    except Exception as e:
        print(f"[FallDetectionController] Error saving snapshot: {e}")
        return None

@router.post("/analyze-frame")
async def analyze_fall_frame(
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    angle_threshold: float = Form(45.0),
    ratio_threshold: float = Form(1.05),
    auto_log: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(_get_optional_user)
):
    """
    Analyzes a single camera frame or snapshot for fall events.
    Supports file upload or base64 data string from live webcams.
    """
    image_bytes = None
    if file is not None:
        image_bytes = await file.read()
    elif image_base64:
        clean_b64 = image_base64
        if "," in clean_b64:
            clean_b64 = clean_b64.split(",")[1]
        image_bytes = base64.b64decode(clean_b64)
    else:
        raise HTTPException(status_code=400, detail="Harap sediakan file gambar atau image_base64")

    try:
        result = process_fall_frame(
            image_bytes=image_bytes,
            angle_threshold=angle_threshold,
            ratio_threshold=ratio_threshold
        )

        # Auto-log incident if enabled and fall is detected
        logged_incident_id = None
        if auto_log and result["has_fall"]:
            snapshot_url = _save_base64_image_to_uploads(result["annotated_image"])
            incident = HSEIncident(
                id=str(uuid.uuid4()),
                user_id=current_user.id if current_user else None,
                incident_type="fall_detection",
                severity="CRITICAL",
                result_image_url=snapshot_url,
                result_json=json.dumps({
                    "persons_count": result["persons_count"],
                    "persons": result["persons"],
                    "angle_threshold": angle_threshold,
                    "ratio_threshold": ratio_threshold
                }),
                persons_count=result["persons_count"],
                violations_count=1,
                model_used="mediapipe-pose-landmarker",
                processing_ms=int(result.get("processing_ms", 0))
            )
            db.add(incident)
            db.commit()
            db.refresh(incident)
            logged_incident_id = incident.id

        result["incident_id"] = logged_incident_id
        return {"success": True, "data": result}
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Analisis frame gagal: {str(err)}")

@router.post("/analyze-video")
async def analyze_fall_video(
    file: UploadFile = File(...),
    angle_threshold: float = Form(45.0),
    ratio_threshold: float = Form(1.05),
    auto_log: bool = Form(True),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(_get_optional_user)
):
    """
    Processes video clip (CCTV recording, MP4, etc.):
    - Frame-by-frame MediaPipe pose extraction
    - Video annotation and timeline generation
    - Automatic incident logging
    """
    video_bytes = await file.read()
    if not video_bytes:
        raise HTTPException(status_code=400, detail="File video kosong")

    try:
        result = process_fall_video(
            video_bytes=video_bytes,
            angle_threshold=angle_threshold,
            ratio_threshold=ratio_threshold
        )

        logged_incident_id = None
        if auto_log and result["has_fall"]:
            snapshot_url = None
            if result.get("snapshot"):
                snapshot_url = _save_base64_image_to_uploads(result["snapshot"])

            incident = HSEIncident(
                id=str(uuid.uuid4()),
                user_id=current_user.id if current_user else None,
                incident_type="fall_detection",
                severity="CRITICAL",
                image_url=result.get("video_url"),
                result_image_url=snapshot_url,
                result_json=json.dumps({
                    "duration_seconds": result.get("duration_seconds"),
                    "total_frames": result.get("total_frames"),
                    "fall_frame_count": result.get("fall_frame_count"),
                    "timeline_events": result.get("timeline_events", [])
                }),
                persons_count=result.get("max_persons", 1),
                violations_count=1,
                model_used="mediapipe-pose-landmarker",
                processing_ms=int(result.get("processing_time_ms", 0))
            )
            db.add(incident)
            db.commit()
            db.refresh(incident)
            logged_incident_id = incident.id

        result["incident_id"] = logged_incident_id
        return {"success": True, "data": result}
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Analisis video gagal: {str(err)}")

@router.get("/incidents")
def get_fall_incidents(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Fetches list of registered fall incidents."""
    query = db.query(HSEIncident).filter(HSEIncident.incident_type == "fall_detection")
    total = query.count()
    items = query.order_by(HSEIncident.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    result_items = []
    for inc in items:
        details = {}
        try:
            if inc.result_json:
                details = json.loads(inc.result_json)
        except Exception:
            pass

        result_items.append({
            "id": inc.id,
            "incident_type": inc.incident_type,
            "severity": inc.severity,
            "image_url": inc.image_url,
            "result_image_url": inc.result_image_url,
            "persons_count": inc.persons_count,
            "violations_count": inc.violations_count,
            "model_used": inc.model_used,
            "processing_ms": inc.processing_ms,
            "details": details,
            "created_at": inc.created_at.isoformat() if inc.created_at else None
        })

    return {
        "success": True,
        "total": total,
        "page": page,
        "limit": limit,
        "items": result_items
    }

@router.post("/log-incident")
def manual_log_fall_incident(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(_get_optional_user)
):
    """Allows manual/client-triggered logging of a confirmed fall event."""
    snapshot_b64 = payload.get("snapshot")
    snapshot_url = None
    if snapshot_b64:
        snapshot_url = _save_base64_image_to_uploads(snapshot_b64)

    incident = HSEIncident(
        id=str(uuid.uuid4()),
        user_id=current_user.id if current_user else None,
        incident_type="fall_detection",
        severity="CRITICAL",
        result_image_url=snapshot_url,
        result_json=json.dumps(payload.get("details", {})),
        persons_count=payload.get("persons_count", 1),
        violations_count=1,
        model_used="mediapipe-pose-landmarker",
        processing_ms=payload.get("processing_ms", 0)
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    return {
        "success": True,
        "message": "Insiden jatuh berhasil dicatat ke sistem keselamatan K3",
        "incident_id": incident.id
    }

@router.delete("/incidents/{incident_id}")
def delete_fall_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(_get_optional_user)
):
    """Deletes an incident log record."""
    inc = db.query(HSEIncident).filter(
        HSEIncident.id == incident_id,
        HSEIncident.incident_type == "fall_detection"
    ).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Insiden tidak ditemukan")
    db.delete(inc)
    db.commit()
    return {"success": True, "message": "Log insiden berhasil dihapus"}
