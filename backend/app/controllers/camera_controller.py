import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.database.database import get_db
from backend.app.database.models import Camera, User
from backend.app.core.deps import get_current_user
from backend.app.services.camera_service import test_camera_connection, generate_mjpeg_feed

router = APIRouter(prefix="/api/v1/cameras", tags=["CCTV Cameras"])

# Presets helper for popular camera brands
BRAND_PRESETS = {
    "hikvision": "rtsp://{username}:{password}@{ip}:554/Streaming/Channels/101",
    "dahua": "rtsp://{username}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
    "uniview": "rtsp://{username}:{password}@{ip}:554/unicast/c1/s0/live",
    "generic": "rtsp://{username}:{password}@{ip}:554/live"
}

@router.get("")
def list_cameras(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cameras = db.query(Camera).filter(Camera.is_active == True).order_by(Camera.created_at.desc()).all()
    items = []
    for c in cameras:
        items.append({
            "id": c.id,
            "name": c.name,
            "stream_url": c.stream_url,
            "location": c.location,
            "camera_type": c.camera_type,
            "preset_brand": c.preset_brand,
            "enable_ai_overlay": c.enable_ai_overlay,
            "ai_module": c.ai_module,
            "status": c.status,
            "created_at": c.created_at
        })
    return {
        "success": True,
        "total": len(items),
        "data": items,
        "brand_presets": BRAND_PRESETS
    }

@router.post("")
def add_camera(
    name: str = Body(...),
    stream_url: str = Body(...),
    location: str = Body("Main Facility"),
    camera_type: str = Body("rtsp"),
    preset_brand: str = Body("generic"),
    enable_ai_overlay: bool = Body(True),
    ai_module: str = Body("hse"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_camera = Camera(
        user_id=current_user.id,
        name=name,
        stream_url=stream_url,
        location=location,
        camera_type=camera_type,
        preset_brand=preset_brand,
        enable_ai_overlay=enable_ai_overlay,
        ai_module=ai_module,
        status="ONLINE",
        is_active=True
    )
    db.add(new_camera)
    db.commit()
    db.refresh(new_camera)

    return {
        "success": True,
        "message": "Camera added successfully",
        "data": {
            "id": new_camera.id,
            "name": new_camera.name,
            "stream_url": new_camera.stream_url,
            "location": new_camera.location,
            "status": new_camera.status
        }
    }

@router.post("/test-connection")
def test_connection(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stream_url = payload.get("stream_url", "") if isinstance(payload, dict) else str(payload)
    res = test_camera_connection(stream_url)
    return {
        "success": res.get("online", False),
        "data": res
    }

@router.get("/{camera_id}")
def get_camera_detail(
    camera_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cam = db.query(Camera).filter(Camera.id == camera_id, Camera.is_active == True).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    return {
        "success": True,
        "data": {
            "id": cam.id,
            "name": cam.name,
            "stream_url": cam.stream_url,
            "location": cam.location,
            "camera_type": cam.camera_type,
            "preset_brand": cam.preset_brand,
            "enable_ai_overlay": cam.enable_ai_overlay,
            "ai_module": cam.ai_module,
            "status": cam.status,
            "created_at": cam.created_at
        }
    }

@router.put("/{camera_id}")
def update_camera(
    camera_id: str,
    name: Optional[str] = Body(None),
    stream_url: Optional[str] = Body(None),
    location: Optional[str] = Body(None),
    enable_ai_overlay: Optional[bool] = Body(None),
    ai_module: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cam = db.query(Camera).filter(Camera.id == camera_id, Camera.is_active == True).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    if name is not None:
        cam.name = name
    if stream_url is not None:
        cam.stream_url = stream_url
    if location is not None:
        cam.location = location
    if enable_ai_overlay is not None:
        cam.enable_ai_overlay = enable_ai_overlay
    if ai_module is not None:
        cam.ai_module = ai_module

    db.commit()
    db.refresh(cam)

    return {
        "success": True,
        "message": "Camera updated successfully",
        "data": {
            "id": cam.id,
            "name": cam.name,
            "stream_url": cam.stream_url,
            "location": cam.location,
            "enable_ai_overlay": cam.enable_ai_overlay,
            "ai_module": cam.ai_module
        }
    }

@router.delete("/{camera_id}")
def delete_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    cam.is_active = False
    db.commit()

    return {
        "success": True,
        "message": f"Camera {camera_id} deleted successfully"
    }

@router.get("/{camera_id}/feed")
def get_camera_live_feed(
    camera_id: str,
    db: Session = Depends(get_db)
):
    """
    Live MJPEG stream feed endpoint for HTML <img :src="feed_url" /> tags.
    """
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    return StreamingResponse(
        generate_mjpeg_feed(
            stream_url=cam.stream_url,
            enable_ai_overlay=cam.enable_ai_overlay,
            ai_module=cam.ai_module,
            db_session=db
        ),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
