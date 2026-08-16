import json
import csv
import io
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.database.database import get_db
from backend.app.database.models import CVConfig, HSEZoneConfig, HSEIncident, HSEPPERule, User
from backend.app.core.deps import get_current_user
from backend.app.services.hse_service import (
    process_ppe_check,
    process_danger_zone_alert,
    process_near_miss_log
)
from backend.app.services.video_processor_service import process_video_file

router = APIRouter(prefix="/api/v1/hse", tags=["HSE Safety Compliance"])

def _is_video_upload(file: UploadFile) -> bool:
    if file.content_type and file.content_type.startswith("video/"):
        return True
    if file.filename:
        ext = file.filename.lower().split(".")[-1]
        if ext in ["mp4", "mov", "avi", "webm", "mkv"]:
            return True
    return False

def _get_or_create_hse_config(db: Session, user_id: Optional[int] = None) -> CVConfig:
    config = db.query(CVConfig).filter(
        CVConfig.module == "hse",
        CVConfig.is_active == True
    ).first()
    
    if not config:
        config = CVConfig(
            module="hse",
            user_id=user_id,
            model_name="yolov8n",
            confidence=0.4,
            iou_threshold=0.45,
            target_classes=json.dumps(["person"]),
            is_active=True
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

def _get_or_create_default_ppe_rule(db: Session, user_id: Optional[int] = None) -> HSEPPERule:
    rule = db.query(HSEPPERule).filter(HSEPPERule.is_active == True).first()
    if not rule:
        rule = HSEPPERule(
            user_id=user_id,
            rule_name="Standard Warehouse Safety PPE",
            require_helmet=True,
            require_vest=True,
            require_mask=False,
            require_gloves=False,
            require_boots=False,
            is_active=True
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
    return rule

@router.get("/config")
def get_hse_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    config = _get_or_create_hse_config(db, current_user.id)
    return {
        "success": True,
        "data": {
            "id": config.id,
            "module": config.module,
            "model_name": config.model_name,
            "confidence": config.confidence,
            "iou_threshold": config.iou_threshold,
            "target_classes": json.loads(config.target_classes or "[]"),
            "is_active": config.is_active,
            "updated_at": config.updated_at
        }
    }

@router.patch("/config")
def update_hse_config(
    model_name: Optional[str] = None,
    confidence: Optional[float] = None,
    iou_threshold: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    config = _get_or_create_hse_config(db, current_user.id)
    if model_name is not None:
        config.model_name = model_name
    if confidence is not None:
        config.confidence = max(0.05, min(1.0, confidence))
    if iou_threshold is not None:
        config.iou_threshold = max(0.05, min(1.0, iou_threshold))

    db.commit()
    db.refresh(config)

    return {
        "success": True,
        "message": "HSE configuration updated successfully",
        "data": {
            "model_name": config.model_name,
            "confidence": config.confidence,
            "iou_threshold": config.iou_threshold
        }
    }

# --- Polygon Zone Endpoints ---

@router.get("/zones")
def get_hse_zones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    zones = db.query(HSEZoneConfig).filter(HSEZoneConfig.is_active == True).all()
    items = []
    for z in zones:
        items.append({
            "id": z.id,
            "zone_name": z.zone_name,
            "zone_type": z.zone_type,
            "polygon_points": json.loads(z.polygon_points or "[]"),
            "camera_id": z.camera_id,
            "color_hex": z.color_hex,
            "is_active": z.is_active,
            "created_at": z.created_at
        })
    return {
        "success": True,
        "data": items
    }

@router.post("/zones")
def create_hse_zone(
    zone_name: str = Body(...),
    zone_type: str = Body("danger"),
    polygon_points: list = Body(...),
    camera_id: str = Body("default"),
    color_hex: str = Body("#FF0000"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_zone = HSEZoneConfig(
        user_id=current_user.id,
        zone_name=zone_name,
        zone_type=zone_type,
        polygon_points=json.dumps(polygon_points),
        camera_id=camera_id,
        color_hex=color_hex,
        is_active=True
    )
    db.add(new_zone)
    db.commit()
    db.refresh(new_zone)

    return {
        "success": True,
        "message": "Zone created successfully",
        "data": {
            "id": new_zone.id,
            "zone_name": new_zone.zone_name,
            "zone_type": new_zone.zone_type,
            "polygon_points": polygon_points
        }
    }

@router.put("/zones/batch")
def batch_sync_hse_zones(
    zones: list = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Deactivate existing active zones and insert new list
    db.query(HSEZoneConfig).update({"is_active": False})
    db.commit()

    created_zones = []
    for z in zones:
        new_z = HSEZoneConfig(
            user_id=current_user.id,
            zone_name=z.get("zone_name", "Zone"),
            zone_type=z.get("zone_type", "danger"),
            polygon_points=json.dumps(z.get("polygon_points", [])),
            camera_id=z.get("camera_id", "default"),
            color_hex=z.get("color_hex", "#FF0000"),
            is_active=True
        )
        db.add(new_z)
        created_zones.append(new_z)

    db.commit()

    return {
        "success": True,
        "message": f"Successfully synchronized {len(created_zones)} zones",
        "total_zones": len(created_zones)
    }

@router.delete("/zones/{zone_id}")
def delete_hse_zone(
    zone_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    zone = db.query(HSEZoneConfig).filter(HSEZoneConfig.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    
    db.delete(zone)
    db.commit()

    return {
        "success": True,
        "message": f"Zone {zone_id} deleted successfully"
    }

# --- PPE Rules Endpoints ---

@router.get("/ppe-rules")
def get_ppe_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    rule = _get_or_create_default_ppe_rule(db, current_user.id)
    return {
        "success": True,
        "data": {
            "id": rule.id,
            "rule_name": rule.rule_name,
            "require_helmet": rule.require_helmet,
            "require_vest": rule.require_vest,
            "require_mask": rule.require_mask,
            "require_gloves": rule.require_gloves,
            "require_boots": rule.require_boots,
            "is_active": rule.is_active,
            "updated_at": rule.updated_at
        }
    }

@router.put("/ppe-rules")
def update_ppe_rules(
    rule_name: Optional[str] = Body(None),
    require_helmet: Optional[bool] = Body(None),
    require_vest: Optional[bool] = Body(None),
    require_mask: Optional[bool] = Body(None),
    require_gloves: Optional[bool] = Body(None),
    require_boots: Optional[bool] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    rule = _get_or_create_default_ppe_rule(db, current_user.id)
    if rule_name is not None:
        rule.rule_name = rule_name
    if require_helmet is not None:
        rule.require_helmet = require_helmet
    if require_vest is not None:
        rule.require_vest = require_vest
    if require_mask is not None:
        rule.require_mask = require_mask
    if require_gloves is not None:
        rule.require_gloves = require_gloves
    if require_boots is not None:
        rule.require_boots = require_boots

    db.commit()
    db.refresh(rule)

    return {
        "success": True,
        "message": "PPE rule updated successfully",
        "data": {
            "rule_name": rule.rule_name,
            "require_helmet": rule.require_helmet,
            "require_vest": rule.require_vest,
            "require_mask": rule.require_mask,
            "require_gloves": rule.require_gloves,
            "require_boots": rule.require_boots
        }
    }

# --- Core HSE Verification Endpoints ---

@router.post("/ppe-check")
async def ppe_check_endpoint(
    image: UploadFile = File(...),
    confidence_override: Optional[float] = Form(None),
    model_name_override: Optional[str] = Form(None),
    output_mode: Optional[str] = Form("image"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty image uploaded")

    config = _get_or_create_hse_config(db, current_user.id)
    rule = _get_or_create_default_ppe_rule(db, current_user.id)
    
    conf = confidence_override if confidence_override is not None else config.confidence
    model = model_name_override if model_name_override else config.model_name
    ppe_dict = {
        "require_helmet": rule.require_helmet,
        "require_vest": rule.require_vest,
        "require_mask": rule.require_mask
    }

    if output_mode == "video" and _is_video_upload(image):
        result = process_video_file(
            video_bytes=contents,
            module="hse",
            action="ppe_check",
            options={"ppe_rules": ppe_dict, "confidence": conf}
        )
    else:
        result = process_ppe_check(
            image_bytes=contents,
            ppe_rules=ppe_dict,
            confidence=conf,
            model_name=model
        )

    if result["violations_count"] > 0:
        incident = HSEIncident(
            user_id=current_user.id,
            incident_type="ppe_violation",
            severity="MEDIUM" if result["violations_count"] == 1 else "HIGH",
            result_json=json.dumps(result),
            persons_count=result["total_persons"],
            violations_count=result["violations_count"],
            model_used=model,
            processing_ms=result["processing_ms"]
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        result["incident_id"] = incident.id

    return {
        "success": True,
        "data": result
    }

@router.post("/danger-zone-alert")
async def danger_zone_alert_endpoint(
    image: UploadFile = File(...),
    confidence_override: Optional[float] = Form(None),
    model_name_override: Optional[str] = Form(None),
    output_mode: Optional[str] = Form("image"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty image uploaded")

    config = _get_or_create_hse_config(db, current_user.id)
    db_zones = db.query(HSEZoneConfig).filter(HSEZoneConfig.is_active == True).all()
    
    zones_list = [
        {
            "zone_name": z.zone_name,
            "zone_type": z.zone_type,
            "polygon_points": json.loads(z.polygon_points or "[]")
        } for z in db_zones
    ]

    conf = confidence_override if confidence_override is not None else config.confidence
    model = model_name_override if model_name_override else config.model_name

    if output_mode == "video" and _is_video_upload(image):
        result = process_video_file(
            video_bytes=contents,
            module="hse",
            action="danger_zone",
            options={"danger_zones": zones_list, "confidence": conf}
        )
    else:
        result = process_danger_zone_alert(
            image_bytes=contents,
            zones_list=zones_list,
            confidence=conf,
            model_name=model
        )

    if result["has_intrusion"]:
        incident = HSEIncident(
            user_id=current_user.id,
            incident_type="danger_zone",
            severity="HIGH",
            result_json=json.dumps(result),
            persons_count=result["intrusions_count"],
            violations_count=result["intrusions_count"],
            model_used=model,
            processing_ms=result["processing_ms"]
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        result["incident_id"] = incident.id

    return {
        "success": True,
        "data": result
    }

@router.post("/near-miss-log")
async def near_miss_log_endpoint(
    image: UploadFile = File(...),
    confidence_override: Optional[float] = Form(None),
    model_name_override: Optional[str] = Form(None),
    output_mode: Optional[str] = Form("image"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty image uploaded")

    config = _get_or_create_hse_config(db, current_user.id)
    rule = _get_or_create_default_ppe_rule(db, current_user.id)
    db_zones = db.query(HSEZoneConfig).filter(HSEZoneConfig.is_active == True).all()

    zones_list = [
        {
            "zone_name": z.zone_name,
            "zone_type": z.zone_type,
            "polygon_points": json.loads(z.polygon_points or "[]")
        } for z in db_zones
    ]
    ppe_dict = {
        "require_helmet": rule.require_helmet,
        "require_vest": rule.require_vest
    }

    conf = confidence_override if confidence_override is not None else config.confidence
    model = model_name_override if model_name_override else config.model_name

    if output_mode == "video" and _is_video_upload(image):
        result = process_video_file(
            video_bytes=contents,
            module="hse",
            action="near_miss",
            options={"danger_zones": zones_list, "ppe_rules": ppe_dict, "confidence": conf}
        )
    else:
        result = process_near_miss_log(
            image_bytes=contents,
            zones_list=zones_list,
            ppe_rules=ppe_dict,
            confidence=conf,
            model_name=model
        )

    if result["is_near_miss"]:
        incident = HSEIncident(
            user_id=current_user.id,
            incident_type="near_miss",
            severity=result["severity"],
            result_json=json.dumps(result),
            persons_count=result["ppe_summary"]["total_persons"],
            violations_count=result["ppe_summary"]["violations_count"] + result["zone_summary"]["intrusions_count"],
            model_used=model,
            processing_ms=result["processing_ms"]
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        result["incident_id"] = incident.id

    return {
        "success": True,
        "data": result
    }

@router.get("/incidents")
def get_hse_incidents(
    page: int = 1,
    limit: int = 20,
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(HSEIncident)
    if severity:
        query = query.filter(HSEIncident.severity == severity)
    
    total = query.count()
    records = query.order_by(HSEIncident.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    items = []
    for r in records:
        parsed_json = json.loads(r.result_json) if r.result_json else {}
        items.append({
            "id": r.id,
            "incident_type": r.incident_type,
            "severity": r.severity,
            "persons_count": r.persons_count,
            "violations_count": r.violations_count,
            "model_used": r.model_used,
            "processing_ms": r.processing_ms,
            "created_at": r.created_at,
            "annotated_image": parsed_json.get("annotated_image")
        })

    return {
        "success": True,
        "total": total,
        "page": page,
        "limit": limit,
        "items": items
    }

@router.get("/incidents/{incident_id}")
def get_hse_incident_detail(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = db.query(HSEIncident).filter(HSEIncident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident record not found")
    
    return {
        "success": True,
        "data": {
            "id": incident.id,
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "persons_count": incident.persons_count,
            "violations_count": incident.violations_count,
            "model_used": incident.model_used,
            "processing_ms": incident.processing_ms,
            "created_at": incident.created_at,
            "result": json.loads(incident.result_json) if incident.result_json else {}
        }
    }

@router.delete("/incidents/{incident_id}")
def delete_hse_incident(
    incident_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = db.query(HSEIncident).filter(HSEIncident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident record not found")
    
    db.delete(incident)
    db.commit()

    return {
        "success": True,
        "message": f"Incident record {incident_id} deleted successfully"
    }

@router.get("/export")
def export_hse_incidents_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    records = db.query(HSEIncident).order_by(HSEIncident.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Incident Type", "Severity", "Persons Count", "Violations", "Model", "Processing MS", "Created At"])

    for r in records:
        writer.writerow([r.id, r.incident_type, r.severity, r.persons_count, r.violations_count, r.model_used, r.processing_ms, r.created_at])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=hse_incidents.csv"}
    )
