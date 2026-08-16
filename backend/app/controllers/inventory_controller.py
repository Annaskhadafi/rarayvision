import json
import csv
import io
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.database.database import get_db
from backend.app.database.models import CVConfig, InventoryScan, User
from backend.app.core.deps import get_current_user
from backend.app.services.inventory_service import (
    process_count_boxes,
    process_defect_check,
    process_shelf_occupancy
)
from backend.app.services.video_processor_service import process_video_file

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory Audit"])

def _is_video_upload(file: UploadFile) -> bool:
    if file.content_type and file.content_type.startswith("video/"):
        return True
    if file.filename:
        ext = file.filename.lower().split(".")[-1]
        if ext in ["mp4", "mov", "avi", "webm", "mkv"]:
            return True
    return False

def _get_or_create_config(db: Session, user_id: Optional[int] = None) -> CVConfig:
    config = db.query(CVConfig).filter(
        CVConfig.module == "inventory",
        CVConfig.is_active == True
    ).first()
    
    if not config:
        config = CVConfig(
            module="inventory",
            user_id=user_id,
            model_name="yolov8n",
            confidence=0.4,
            iou_threshold=0.45,
            target_classes=json.dumps(["box", "suitcase", "container", "package"]),
            is_active=True
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

@router.get("/config")
def get_inventory_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    config = _get_or_create_config(db, current_user.id)
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
def update_inventory_config(
    model_name: Optional[str] = None,
    confidence: Optional[float] = None,
    iou_threshold: Optional[float] = None,
    target_classes: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    config = _get_or_create_config(db, current_user.id)
    
    if model_name is not None:
        config.model_name = model_name
    if confidence is not None:
        config.confidence = max(0.05, min(1.0, confidence))
    if iou_threshold is not None:
        config.iou_threshold = max(0.05, min(1.0, iou_threshold))
    if target_classes is not None:
        config.target_classes = json.dumps(target_classes)

    db.commit()
    db.refresh(config)

    return {
        "success": True,
        "message": "Inventory configuration updated successfully",
        "data": {
            "model_name": config.model_name,
            "confidence": config.confidence,
            "iou_threshold": config.iou_threshold,
            "target_classes": json.loads(config.target_classes or "[]")
        }
    }

@router.post("/count-boxes")
async def count_boxes_endpoint(
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

    config = _get_or_create_config(db, current_user.id)
    conf = confidence_override if confidence_override is not None else config.confidence
    model = model_name_override if model_name_override else config.model_name
    targets = json.loads(config.target_classes or "[]")

    if output_mode == "video" and _is_video_upload(image):
        result = process_video_file(
            video_bytes=contents,
            module="inventory",
            action="count_boxes",
            options={"confidence": conf}
        )
    else:
        result = process_count_boxes(
            image_bytes=contents,
            confidence=conf,
            iou_threshold=config.iou_threshold,
            target_classes=targets,
            model_name=model
        )

    # Save to history DB
    scan_record = InventoryScan(
        user_id=current_user.id if current_user else None,
        scan_type="count_boxes",
        result_json=json.dumps(result),
        total_count=result["total_count"],
        model_used=model,
        confidence_used=conf,
        processing_ms=result["processing_ms"]
    )
    db.add(scan_record)
    db.commit()
    db.refresh(scan_record)

    result["scan_id"] = scan_record.id

    return {
        "success": True,
        "data": result
    }

@router.post("/defect-check")
async def defect_check_endpoint(
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

    config = _get_or_create_config(db, current_user.id)
    conf = confidence_override if confidence_override is not None else config.confidence
    model = model_name_override if model_name_override else config.model_name

    if output_mode == "video" and _is_video_upload(image):
        result = process_video_file(
            video_bytes=contents,
            module="inventory",
            action="defect_check",
            options={"confidence": conf}
        )
    else:
        result = process_defect_check(
            image_bytes=contents,
            confidence=conf,
            model_name=model
        )

    scan_record = InventoryScan(
        user_id=current_user.id if current_user else None,
        scan_type="defect_check",
        result_json=json.dumps(result),
        total_count=result["defects_count"],
        model_used=model,
        confidence_used=conf,
        processing_ms=result["processing_ms"]
    )
    db.add(scan_record)
    db.commit()
    db.refresh(scan_record)

    result["scan_id"] = scan_record.id

    return {
        "success": True,
        "data": result
    }

@router.post("/shelf-occupancy")
async def shelf_occupancy_endpoint(
    image: UploadFile = File(...),
    grid_rows: int = Form(3),
    grid_cols: int = Form(4),
    confidence_override: Optional[float] = Form(None),
    model_name_override: Optional[str] = Form(None),
    output_mode: Optional[str] = Form("image"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty image uploaded")

    config = _get_or_create_config(db, current_user.id)
    conf = confidence_override if confidence_override is not None else config.confidence
    model = model_name_override if model_name_override else config.model_name

    if output_mode == "video" and _is_video_upload(image):
        result = process_video_file(
            video_bytes=contents,
            module="inventory",
            action="shelf_occupancy",
            options={"grid_rows": grid_rows, "grid_cols": grid_cols, "confidence": conf}
        )
    else:
        result = process_shelf_occupancy(
            image_bytes=contents,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            confidence=conf,
            model_name=model
        )

    scan_record = InventoryScan(
        user_id=current_user.id if current_user else None,
        scan_type="shelf_occupancy",
        result_json=json.dumps(result),
        total_count=result["occupied_cells"],
        model_used=model,
        confidence_used=conf,
        processing_ms=result["processing_ms"]
    )
    db.add(scan_record)
    db.commit()
    db.refresh(scan_record)

    result["scan_id"] = scan_record.id

    return {
        "success": True,
        "data": result
    }

@router.get("/history")
def get_inventory_history(
    page: int = 1,
    limit: int = 20,
    scan_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(InventoryScan)
    if scan_type:
        query = query.filter(InventoryScan.scan_type == scan_type)
    
    total = query.count()
    records = query.order_by(InventoryScan.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    items = []
    for r in records:
        parsed_json = json.loads(r.result_json) if r.result_json else {}
        items.append({
            "id": r.id,
            "scan_type": r.scan_type,
            "total_count": r.total_count,
            "model_used": r.model_used,
            "confidence_used": r.confidence_used,
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

@router.get("/history/{scan_id}")
def get_inventory_scan_detail(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    scan = db.query(InventoryScan).filter(InventoryScan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan record not found")
    
    return {
        "success": True,
        "data": {
            "id": scan.id,
            "scan_type": scan.scan_type,
            "total_count": scan.total_count,
            "model_used": scan.model_used,
            "confidence_used": scan.confidence_used,
            "processing_ms": scan.processing_ms,
            "created_at": scan.created_at,
            "result": json.loads(scan.result_json) if scan.result_json else {}
        }
    }

@router.delete("/history/{scan_id}")
def delete_inventory_scan(
    scan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    scan = db.query(InventoryScan).filter(InventoryScan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan record not found")
    
    db.delete(scan)
    db.commit()

    return {
        "success": True,
        "message": f"Scan record {scan_id} deleted successfully"
    }

@router.get("/export")
def export_inventory_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    records = db.query(InventoryScan).order_by(InventoryScan.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Scan Type", "Total Count", "Model", "Confidence", "Processing MS", "Created At"])

    for r in records:
        writer.writerow([r.id, r.scan_type, r.total_count, r.model_used, r.confidence_used, r.processing_ms, r.created_at])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory_scans.csv"}
    )
