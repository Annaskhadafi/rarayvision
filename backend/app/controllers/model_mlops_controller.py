import os
import io
import uuid
import json
import zipfile
import shutil
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

try:
    from backend.app.database.database import get_db
    from backend.app.database.models import MLModel, MLPrediction, MLEndpoint
    from backend.app.services.detection_service import detection_service
    from backend.app.services.s3_service import s3_service
    from backend.app.services.label_studio_service import label_studio_service
    from backend.app.core.config import BASE_DIR
except ImportError:
    from app.database.database import get_db
    from app.database.models import MLModel, MLPrediction, MLEndpoint
    from app.services.detection_service import detection_service
    from app.services.s3_service import s3_service
    from app.services.label_studio_service import label_studio_service
    from app.core.config import BASE_DIR

router = APIRouter(prefix="/api/v1/models", tags=["Object Detection & MLOps"])

class FeedbackRequest(BaseModel):
    feedback: str # "good" or "bad"
    notes: Optional[str] = None

class LabelStudioSyncRequest(BaseModel):
    project_id: Optional[str] = None
    include_good: bool = True
    include_bad: bool = True
    model_id: Optional[int] = None
    endpoint_slug: Optional[str] = None

class ModelUpdateRequest(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    task_type: Optional[str] = None
    framework: Optional[str] = None
    description: Optional[str] = None

class EndpointCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    model_id: Optional[int] = None
    default_conf: float = 0.25
    default_iou: float = 0.45
    is_active: bool = True

class EndpointUpdateRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    model_id: Optional[int] = None
    default_conf: Optional[float] = None
    default_iou: Optional[float] = None
    is_active: Optional[bool] = None

class EndpointSwitchModelRequest(BaseModel):
    model_id: int



# ==========================================
# 1. Prediction & Feedback Endpoints
# ==========================================

@router.post("/predict")
async def predict_object(
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    conf_threshold: float = Form(0.25),
    iou_threshold: float = Form(0.45),
    db: Session = Depends(get_db)
):
    """
    Run object detection using the currently active model.
    Saves original and annotated images to S3, registers prediction in DB,
    and returns prediction_id with bounding boxes and annotated image URL.
    """
    if file:
        image_bytes = await file.read()
        filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}.jpg"
    elif image_url:
        import requests
        try:
            resp = requests.get(image_url, timeout=10)
            resp.raise_for_status()
            image_bytes = resp.content
            filename = os.path.basename(image_url.split("?")[0]) or "remote_image.jpg"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch image from URL: {e}")
    else:
        raise HTTPException(status_code=400, detail="Must provide an image file or image_url")

    # Run detection inference
    try:
        result = detection_service.predict(
            image_bytes,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")

    pred_id = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".jpg"

    # Upload original image to S3
    raw_s3_key = f"datasets/raw/{pred_id}{ext}"
    orig_url = s3_service.upload_bytes(image_bytes, raw_s3_key, content_type="image/jpeg")

    # Upload annotated visual image to S3
    annotated_s3_key = f"datasets/annotated/{pred_id}.jpg"
    annotated_url = s3_service.upload_bytes(result["annotated_bytes"], annotated_s3_key, content_type="image/jpeg")

    # Determine initial feedback status with 10% CV-Ops Human Audit Sampling
    import random
    initial_status = "pending"
    is_audit = False
    if result["top_confidence"] >= 0.88 and result["detection_count"] > 0:
        # 10% random sample for human verification in Label Studio to prevent confirmation bias
        if random.random() < 0.10:
            initial_status = "audit_required"
            is_audit = True
        else:
            initial_status = "auto_labeled"

    # Store prediction record in DB
    pred_record = MLPrediction(
        id=pred_id,
        model_id=result["model_id"],
        model_version=result["model_version"],
        original_image_url=orig_url,
        annotated_image_url=annotated_url,
        detections=json.dumps(result["detections"]),
        top_confidence=result["top_confidence"],
        detection_count=result["detection_count"],
        latency_ms=result["latency_ms"],
        feedback_status=initial_status,
        is_audit_sample=is_audit,
        image_quality=json.dumps(result.get("quality", {})),
        is_synced_to_ls=False
    )
    db.add(pred_record)
    db.commit()

    return {
        "prediction_id": pred_id,
        "model_id": result["model_id"],
        "model_name": result["model_name"],
        "model_version": result["model_version"],
        "original_image_url": orig_url,
        "annotated_image_url": annotated_url,
        "detections": result["detections"],
        "detection_count": result["detection_count"],
        "top_confidence": result["top_confidence"],
        "latency_ms": result["latency_ms"],
        "image_width": result["image_width"],
        "image_height": result["image_height"],
        "quality": result.get("quality", {}),
        "feedback_status": initial_status,
        "is_audit_sample": is_audit
    }


@router.post("/feedback/{prediction_id}")
async def submit_feedback(
    prediction_id: str,
    payload: FeedbackRequest,
    db: Session = Depends(get_db)
):
    """
    Submit user feedback on a prediction:
    'good' -> Accurate prediction, verified for auto-labeling.
    'bad' -> Inaccurate prediction, flagged for Label Studio human review queue.
    """
    record = db.query(MLPrediction).filter(MLPrediction.id == prediction_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Prediction record not found")

    status_val = payload.feedback.lower().strip()
    if status_val not in ["good", "bad", "pending"]:
        raise HTTPException(status_code=400, detail="Feedback must be 'good' or 'bad'")

    record.feedback_status = status_val
    if payload.notes:
        record.feedback_notes = payload.notes
    record.is_synced_to_ls = False # Reset sync flag so it gets picked up in next sync

    db.commit()
    db.refresh(record)

    return {
        "success": True,
        "prediction_id": record.id,
        "feedback_status": record.feedback_status,
        "feedback_notes": record.feedback_notes,
        "message": f"Feedback '{record.feedback_status}' successfully recorded."
    }


# ==========================================
# 2. Model Management & Versioning Endpoints
# ==========================================

@router.get("")
def list_models(db: Session = Depends(get_db)):
    """List all registered models with their active status and metrics."""
    models = db.query(MLModel).order_by(MLModel.created_at.desc()).all()
    results = []
    for m in models:
        metrics = json.loads(m.metrics_summary) if m.metrics_summary else {}
        classes = json.loads(m.classes) if m.classes else []
        results.append({
            "id": m.id,
            "name": m.name,
            "version": m.version,
            "task_type": m.task_type,
            "framework": m.framework,
            "is_active": m.is_active,
            "description": m.description,
            "classes": classes,
            "classes_count": len(classes),
            "metrics": metrics,
            "created_at": m.created_at.isoformat() if m.created_at else None
        })
    return {"models": results}


@router.post("/upload")
async def upload_model(
    name: str = Form(...),
    version: str = Form(...),
    task_type: str = Form("detection"),
    framework: str = Form("yolo"),
    description: Optional[str] = Form(None),
    model_file: UploadFile = File(...),
    onnx_file: Optional[UploadFile] = File(None),
    results_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    Upload a trained model (.pt or .onnx) and optional evaluation results zip.
    Extracts metrics and creates registry entry.
    """
    # Ensure model file extension
    m_ext = os.path.splitext(model_file.filename)[1].lower()
    if m_ext not in [".pt", ".onnx"]:
        raise HTTPException(status_code=400, detail="Model file must be .pt or .onnx")

    # Save model weights file (.pt or .onnx)
    safe_name = f"{name.replace(' ', '_').lower()}_{version.replace(' ', '_').lower()}_{uuid.uuid4().hex[:6]}{m_ext}"
    model_dest = os.path.join(detection_service.models_storage_dir, safe_name)
    with open(model_dest, "wb") as f:
        f.write(await model_file.read())

    # Save accompanying .onnx file if provided
    onnx_dest = None
    if onnx_file:
        o_name = f"{name.replace(' ', '_').lower()}_{version.replace(' ', '_').lower()}_{uuid.uuid4().hex[:6]}.onnx"
        onnx_dest = os.path.join(detection_service.models_storage_dir, o_name)
        with open(onnx_dest, "wb") as f:
            f.write(await onnx_file.read())

    # Try reading classes from YOLO model if .pt
    classes_list = []
    try:
        from ultralytics import YOLO
        y_temp = YOLO(model_dest)
        if hasattr(y_temp, "names") and y_temp.names:
            classes_list = list(y_temp.names.values())
    except Exception as e:
        print(f"[ModelUpload] Note: could not extract classes automatically: {e}")

    # Create DB entry first to get ID
    new_model = MLModel(
        name=name,
        version=version,
        task_type=task_type,
        framework=framework,
        model_path=model_dest,
        onnx_path=onnx_dest,
        classes=json.dumps(classes_list),
        is_active=False,
        description=description,
        metrics_summary=json.dumps({})
    )
    db.add(new_model)
    db.commit()
    db.refresh(new_model)

    # Process evaluation archive if provided
    eval_metrics = {}
    if results_file:
        zip_temp_path = os.path.join(detection_service.evaluations_dir, f"temp_{new_model.id}.zip")
        with open(zip_temp_path, "wb") as f:
            f.write(await results_file.read())
        
        try:
            eval_result = detection_service.process_evaluation_archive(zip_temp_path, new_model.id)
            eval_metrics = eval_result["metrics"]
            new_model.metrics_summary = json.dumps(eval_metrics)
            new_model.evaluation_dir = eval_result["evaluation_dir"]
            db.commit()
        except Exception as e:
            print(f"[ModelUpload] Error processing results zip: {e}")
        finally:
            if os.path.exists(zip_temp_path):
                os.remove(zip_temp_path)

    return {
        "success": True,
        "message": f"Model '{name}' ({version}) uploaded successfully.",
        "model": {
            "id": new_model.id,
            "name": new_model.name,
            "version": new_model.version,
            "classes": classes_list,
            "metrics": eval_metrics
        }
    }


@router.post("/rollback")
def rollback_model(db: Session = Depends(get_db)):
    """Instant 1-Click Rollback to previous active model in production."""
    result = detection_service.rollback_model(db)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/{model_id}/export-onnx")
def export_model_to_onnx(model_id: int, db: Session = Depends(get_db)):
    """Export a PyTorch .pt model to ONNX runtime format for CPU acceleration."""
    result = detection_service.export_to_onnx(model_id, db)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result

@router.put("/{model_id}/activate")
def activate_model(model_id: int, db: Session = Depends(get_db)):
    """Hot-swap the active inference model without restarting the server."""
    result = detection_service.hot_swap_model(model_id, db)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.put("/{model_id}")
def update_model(model_id: int, payload: ModelUpdateRequest, db: Session = Depends(get_db)):
    """Update model metadata (name, version, framework, description, task_type)."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if payload.name is not None and payload.name.strip():
        model.name = payload.name.strip()
    if payload.version is not None and payload.version.strip():
        model.version = payload.version.strip()
    if payload.task_type is not None and payload.task_type.strip():
        model.task_type = payload.task_type.strip()
    if payload.framework is not None and payload.framework.strip():
        model.framework = payload.framework.strip()
    if payload.description is not None:
        model.description = payload.description.strip()

    db.commit()
    db.refresh(model)

    detection_service.invalidate_model_cache(model_id)

    return {
        "success": True,
        "message": f"Model '{model.name}' berhasil diperbarui.",
        "model": {
            "id": model.id,
            "name": model.name,
            "version": model.version,
            "task_type": model.task_type,
            "framework": model.framework,
            "description": model.description
        }
    }


@router.delete("/{model_id}")
def delete_model(model_id: int, force: bool = False, db: Session = Depends(get_db)):
    """Delete a model from registry, unlink from endpoints, and clean filesystem."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    # If it is active, check if there are other models available to auto-activate
    if model.is_active:
        other_model = db.query(MLModel).filter(MLModel.id != model_id).first()
        if other_model:
            detection_service.hot_swap_model(other_model.id, db)
        elif not force:
            raise HTTPException(
                status_code=400,
                detail="Model ini adalah satu-satunya model aktif di sistem. Harap unggah model pengganti sebelum menghapus."
            )

    # Decouple endpoints referencing this model
    endpoints_using = db.query(MLEndpoint).filter(MLEndpoint.model_id == model_id).all()
    for ep in endpoints_using:
        ep.model_id = None
    if endpoints_using:
        db.commit()

    # Invalidate memory cache
    detection_service.invalidate_model_cache(model_id)

    # Remove files safely
    try:
        if model.model_path and os.path.exists(model.model_path):
            os.remove(model.model_path)
        if model.onnx_path and os.path.exists(model.onnx_path):
            os.remove(model.onnx_path)
        if model.evaluation_dir and os.path.exists(model.evaluation_dir):
            shutil.rmtree(model.evaluation_dir, ignore_errors=True)
    except Exception as e:
        print(f"[DeleteModel] File removal error: {e}")

    db.delete(model)
    db.commit()
    return {
        "success": True, 
        "message": f"Model '{model.name} ({model.version})' berhasil dihapus.",
        "unlinked_endpoints": len(endpoints_using)
    }


@router.get("/{model_id}/evaluation")
def get_model_evaluation(model_id: int, db: Session = Depends(get_db)):
    """Get offline training evaluation assets and metrics for a model."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    metrics = json.loads(model.metrics_summary) if model.metrics_summary else {}
    visuals = {}

    eval_dir = model.evaluation_dir or os.path.join(detection_service.evaluations_dir, f"model_{model_id}")
    if os.path.exists(eval_dir):
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
            if os.path.exists(os.path.join(eval_dir, fname)):
                visuals[key] = f"/uploads/evaluations/model_{model_id}/{fname}"

    return {
        "model_id": model.id,
        "name": model.name,
        "version": model.version,
        "metrics": metrics,
        "visuals": visuals
    }


# ==========================================
# 3. Production Analytics & Feedback Dashboard
# ==========================================

@router.get("/analytics/production")
def get_production_analytics(
    model_id: Optional[int] = Query(None),
    endpoint_slug: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get online production statistics filtered by model or endpoint."""
    base_q = db.query(MLPrediction)
    if model_id is not None:
        base_q = base_q.filter(MLPrediction.model_id == model_id)
    if endpoint_slug is not None and endpoint_slug.strip():
        base_q = base_q.filter(MLPrediction.endpoint_slug == endpoint_slug.strip())

    total_preds = base_q.count()
    good_count = base_q.filter(MLPrediction.feedback_status == "good").count()
    bad_count = base_q.filter(MLPrediction.feedback_status == "bad").count()
    auto_count = base_q.filter(MLPrediction.feedback_status == "auto_labeled").count()
    audit_count = base_q.filter(MLPrediction.feedback_status == "audit_required").count()
    pending_count = base_q.filter(MLPrediction.feedback_status == "pending").count()

    unsynced_review_count = base_q.filter(
        MLPrediction.feedback_status == "bad",
        MLPrediction.is_synced_to_ls == False
    ).count()

    unsynced_auto_count = base_q.filter(
        MLPrediction.feedback_status.in_(["good", "auto_labeled"]),
        MLPrediction.is_synced_to_ls == False
    ).count()

    from sqlalchemy import func
    avg_lat = base_q.with_entities(func.avg(MLPrediction.latency_ms)).scalar() or 0.0

    recent_preds = base_q.order_by(MLPrediction.created_at.desc()).limit(12).all()
    recent_items = []
    for p in recent_preds:
        recent_items.append({
            "id": p.id,
            "model_id": p.model_id,
            "model_version": p.model_version,
            "endpoint_slug": p.endpoint_slug or "default",
            "original_image_url": p.original_image_url,
            "annotated_image_url": p.annotated_image_url,
            "detection_count": p.detection_count,
            "top_confidence": p.top_confidence,
            "latency_ms": p.latency_ms,
            "feedback_status": p.feedback_status,
            "is_audit_sample": p.is_audit_sample,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })

    return {
        "total_predictions": total_preds,
        "feedback": {
            "good": good_count,
            "bad": bad_count,
            "auto_labeled": auto_count,
            "audit_required": audit_count,
            "pending": pending_count,
            "accuracy_ratio": round((good_count + auto_count) / total_preds * 100, 1) if total_preds > 0 else 100.0
        },
        "review_queue": {
            "pending_human_review": bad_count,
            "unsynced_to_label_studio": unsynced_review_count,
            "unsynced_auto_labeled": unsynced_auto_count
        },
        "performance": {
            "avg_latency_ms": round(avg_lat, 1),
            "active_model": {
                "id": detection_service.active_model_id,
                "name": detection_service.active_model_name,
                "version": detection_service.active_model_version,
                "classes_count": len(detection_service.active_classes)
            }
        },
        "recent_predictions": recent_items,
        "filter": {
            "model_id": model_id,
            "endpoint_slug": endpoint_slug
        }
    }


# ==========================================
# 4. Data Sync to Label Studio & CVAT Import
# ==========================================

@router.post("/data/sync-label-studio")
def sync_to_label_studio(
    payload: LabelStudioSyncRequest,
    db: Session = Depends(get_db)
):
    """
    Push queued images (flagged 'bad' or 'good'/'auto_labeled') directly to Label Studio
    via its REST API for the monthly or periodic labeling cycle.
    """
    statuses_to_sync = []
    if payload.include_bad:
        statuses_to_sync.append("bad")
    if payload.include_good:
        statuses_to_sync.extend(["good", "auto_labeled"])

    sync_q = db.query(MLPrediction).filter(
        MLPrediction.feedback_status.in_(statuses_to_sync),
        MLPrediction.is_synced_to_ls == False
    )
    if payload.model_id:
        sync_q = sync_q.filter(MLPrediction.model_id == payload.model_id)
    if payload.endpoint_slug:
        sync_q = sync_q.filter(MLPrediction.endpoint_slug == payload.endpoint_slug)
    items = sync_q.limit(200).all()

    if not items:
        return {"success": True, "synced_count": 0, "message": "No pending items to sync."}

    tasks = []
    record_map = {}

    for item in items:
        detections = json.loads(item.detections) if item.detections else []
        task_data = {
            "data": {
                "image": item.original_image_url,
                "prediction_id": item.id,
                "feedback_status": item.feedback_status,
                "feedback_notes": item.feedback_notes or ""
            }
        }

        # If it's good or auto_labeled, add pre-annotations
        if item.feedback_status in ["good", "auto_labeled"] and detections:
            ls_results = label_studio_service.format_detection_to_ls_annotation(detections)
            task_data["predictions"] = [
                {
                    "model_version": item.model_version or "active",
                    "result": ls_results
                }
            ]

        tasks.append(task_data)
        record_map[item.id] = item

    # Push to Label Studio
    result = label_studio_service.push_bulk_tasks(tasks, project_id=payload.project_id)

    if result.get("success"):
        # Mark as synced in DB
        for item in items:
            item.is_synced_to_ls = True
        db.commit()

        return {
            "success": True,
            "synced_count": len(items),
            "message": f"Successfully pushed {len(items)} tasks to Label Studio."
        }
    else:
        return {
            "success": False,
            "error": result.get("error"),
            "message": "Failed to push to Label Studio. Ensure Label Studio is running and API token is valid."
        }


@router.post("/data/import-cvat")
async def import_cvat_dataset(
    dataset_name: Optional[str] = Form(None),
    coco_json_file: UploadFile = File(...),
    images_zip_file: UploadFile = File(...),
    project_id: Optional[str] = Form(None)
):
    """
    Import CVAT COCO dataset:
    1. Creates a dedicated folder in S3: datasets/{dataset_folder}/images/
    2. Uploads all images into that dedicated S3 folder
    3. Converts COCO bounding boxes into Label Studio tasks.json
    4. Saves label_studio_tasks.json in the S3 folder
    5. Returns S3 URI, Folder Prefix, Bucket, and Tasks URL ready to COPY directly into Label Studio!
    """
    from datetime import datetime
    import re
    from backend.app.services.s3_service import get_s3_credentials

    # Sanitize dataset name
    raw_name = dataset_name or "cvat_dataset"
    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_name).strip('_').lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{slug}_{timestamp}"
    s3_folder_prefix = f"datasets/{folder_name}/images"

    coco_content = await coco_json_file.read()
    try:
        coco_json = json.loads(coco_content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid COCO JSON file: {e}")

    import tempfile
    import concurrent.futures

    # Stream multi-GB zip to disk in 8MB chunks to prevent memory explosion & timeouts
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = temp_zip.name

    try:
        while chunk := await images_zip_file.read(1024 * 1024 * 8):
            temp_zip.write(chunk)
        temp_zip.close()

        image_url_mapping = {}
        uploaded_files = []

        endpoint, bucket, _, region, _, _ = get_s3_credentials()

        with zipfile.ZipFile(temp_zip_path, "r") as zf:
            valid_members = [
                m for m in zf.namelist()
                if os.path.basename(m) and not m.endswith("/") and not m.startswith("__MACOSX")
            ]

            def upload_single_member(member_name):
                fname = os.path.basename(member_name)
                f_bytes = zf.read(member_name)
                s3_key = f"{s3_folder_prefix}/{fname}"
                ext = os.path.splitext(fname)[1].lower()
                c_type = "image/jpeg"
                if ext == ".png":
                    c_type = "image/png"
                elif ext == ".webp":
                    c_type = "image/webp"
                url = s3_service.upload_bytes(f_bytes, s3_key, content_type=c_type)
                return fname, url

            # Upload images concurrently with 12 threads for 5-10x speedup
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
                future_to_member = {executor.submit(upload_single_member, m): m for m in valid_members}
                for future in concurrent.futures.as_completed(future_to_member):
                    try:
                        fname, accessible_url = future.result()
                        if accessible_url:
                            image_url_mapping[fname] = accessible_url
                            uploaded_files.append(fname)
                    except Exception as err:
                        print(f"[CVATImport] Error uploading {future_to_member[future]}: {err}")

        # Convert COCO annotations to Label Studio format
        tasks = label_studio_service.convert_coco_to_label_studio(coco_json, image_url_mapping)

        # Also save tasks.json in S3 folder for direct import in Label Studio
        tasks_json_bytes = json.dumps(tasks, indent=2).encode("utf-8")
        tasks_s3_key = f"datasets/{folder_name}/label_studio_tasks.json"
        tasks_url = s3_service.upload_bytes(tasks_json_bytes, tasks_s3_key, content_type="application/json")

        # Save COCO annotations (with S3 image URLs embedded) for RF-DETR & PyTorch COCO Evaluators
        coco_annotations_s3_key = f"datasets/{folder_name}/annotations_coco.json"
        coco_s3_bytes = json.dumps(coco_json, indent=2).encode("utf-8")
        coco_url = s3_service.upload_bytes(coco_s3_bytes, coco_annotations_s3_key, content_type="application/json")

        # Generate YOLO data.yaml configuration file
        import yaml
        cat_list = coco_json.get("categories", [])
        if cat_list:
            cat_names = [c.get("name") for c in sorted(cat_list, key=lambda x: x.get("id", 0))]
            yolo_names = {i: name for i, name in enumerate(cat_names)}
        else:
            cat_names = ["object"]
            yolo_names = {0: "object"}

        yolo_yaml_data = {
            "path": f"./{folder_name}",
            "train": "images/train",
            "val": "images/val",
            "nc": len(cat_names),
            "names": yolo_names
        }
        yolo_yaml_bytes = yaml.dump(yolo_yaml_data, sort_keys=False).encode("utf-8")
        yolo_yaml_s3_key = f"datasets/{folder_name}/data.yaml"
        yolo_yaml_url = s3_service.upload_bytes(yolo_yaml_bytes, yolo_yaml_s3_key, content_type="text/yaml")

        # Optionally push directly if Label Studio instance is configured
        ls_push_result = None
        if project_id:
            ls_push_result = label_studio_service.push_bulk_tasks(tasks, project_id=project_id)

        s3_uri = f"s3://{bucket}/{s3_folder_prefix}/"

        # Ready-to-run Colab code snippet
        colab_yolo_snippet = f"""# ==========================================
# 🚀 GOOGLE COLAB TRAINING PIPELINE (YOLOv8 / YOLO11)
# Dataset: {folder_name}
# ==========================================
!pip install -q ultralytics

# 1. Download data.yaml
!curl -fsSL -o data.yaml "{yolo_yaml_url}"

# 2. Download tasks / annotations
!curl -fsSL -o dataset_tasks.json "{tasks_url}"

# 3. Train Model
from ultralytics import YOLO

model = YOLO("yolo11n.pt") # atau yolov8m.pt / rfdetr
results = model.train(data="data.yaml", epochs=50, imgsz=640)

# 4. Validasi Model
metrics = model.val()
print("mAP50-95:", metrics.box.map)

# 5. Export weights untuk diunggah kembali ke Raray Vision
# Model weights tersimpan di: runs/detect/train/weights/best.pt
model.export(format="onnx")
"""

        colab_rfdetr_snippet = f"""# ==========================================
# 🎯 GOOGLE COLAB TRAINING PIPELINE (RF-DETR / RT-DETR)
# Dataset: {folder_name}
# ==========================================
!pip install -q ultralytics

# 1. Download data.yaml & COCO annotations
!curl -fsSL -o data.yaml "{yolo_yaml_url}"
!curl -fsSL -o annotations_coco.json "{coco_url}"

# 2. Train RT-DETR / RF-DETR
from ultralytics import RTDETR

model = RTDETR("rtdetr-l.pt")
results = model.train(data="data.yaml", epochs=50, imgsz=640)

# 3. Validasi Model
metrics = model.val()
print("Validation Results:", metrics)

# 4. Export ONNX untuk Hot-Swap di Raray Vision
model.export(format="onnx")
"""

        return {
            "success": True,
            "dataset_folder": folder_name,
            "s3_bucket": bucket,
            "s3_folder_prefix": f"{s3_folder_prefix}/",
            "s3_uri": s3_uri,
            "s3_endpoint": endpoint,
            "tasks_json_url": tasks_url,
            "coco_json_url": coco_url,
            "yolo_yaml_url": yolo_yaml_url,
            "images_uploaded_count": len(uploaded_files),
            "tasks_created_count": len(tasks),
            "categories": cat_names,
            "colab_training": {
                "data_yaml_url": yolo_yaml_url,
                "coco_json_url": coco_url,
                "yolo_code": colab_yolo_snippet,
                "rfdetr_code": colab_rfdetr_snippet
            },
            "label_studio_instructions": {
                "method_1_cloud_storage": {
                    "storage_type": "AWS S3",
                    "bucket_name": bucket,
                    "bucket_prefix": f"{s3_folder_prefix}/",
                    "s3_endpoint": endpoint,
                    "use_pre_signed_urls": True
                },
                "method_2_direct_import_url": tasks_url
            },
            "message": f"Dataset berhasil diunggah ke folder S3 '{folder_name}'. URL untuk Label Studio, YOLO, dan RF-DETR Colab siap digunakan."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengimpor dataset: {str(e)}")
    finally:
        if os.path.exists(temp_zip_path):
            try:
                os.remove(temp_zip_path)
            except Exception:
                pass


@router.post("/predict-video")
async def predict_video_endpoint(
    video: UploadFile = File(...),
    conf_threshold: float = Form(0.25),
    iou_threshold: float = Form(0.45)
):
    """
    Run object detection on an uploaded video file frame-by-frame.
    Returns URL to web-compatible MP4 with rendered bounding boxes and stats.
    """
    video_bytes = await video.read()
    if not video_bytes:
        raise HTTPException(status_code=400, detail="File video kosong")

    import asyncio
    try:
        result = await asyncio.to_thread(
            detection_service.predict_video,
            video_bytes,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold
        )
        return {
            "status": "success",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memproses video: {str(e)}")


# ==========================================
# 5. Serving Endpoints (Multi-Model API Hub)
# ==========================================

import re

def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-') or f"ep-{uuid.uuid4().hex[:6]}"

@router.get("/endpoints")
def list_endpoints(db: Session = Depends(get_db)):
    """List all custom serving endpoints with joined model information."""
    endpoints = db.query(MLEndpoint).order_by(MLEndpoint.created_at.desc()).all()
    results = []
    for ep in endpoints:
        m = db.query(MLModel).filter(MLModel.id == ep.model_id).first() if ep.model_id else None
        results.append({
            "id": ep.id,
            "name": ep.name,
            "slug": ep.slug,
            "description": ep.description,
            "model_id": ep.model_id,
            "model_name": m.name if m else "(Tidak Ada Model)",
            "model_version": m.version if m else "-",
            "model_framework": m.framework if m else "-",
            "is_active": ep.is_active,
            "default_conf": ep.default_conf,
            "default_iou": ep.default_iou,
            "total_requests": ep.total_requests or 0,
            "last_accessed_at": ep.last_accessed_at.isoformat() if ep.last_accessed_at else None,
            "created_at": ep.created_at.isoformat() if ep.created_at else None,
            "predict_url": f"/api/v1/models/endpoints/{ep.slug}/predict",
            "predict_video_url": f"/api/v1/models/endpoints/{ep.slug}/predict-video"
        })
    return {"endpoints": results}


@router.post("/endpoints")
def create_endpoint(payload: EndpointCreateRequest, db: Session = Depends(get_db)):
    """Create a new custom serving endpoint assigned to a model."""
    raw_slug = payload.slug if (payload.slug and payload.slug.strip()) else slugify(payload.name)
    clean_slug = slugify(raw_slug)

    # Check slug uniqueness
    existing = db.query(MLEndpoint).filter(MLEndpoint.slug == clean_slug).first()
    if existing:
        clean_slug = f"{clean_slug}-{uuid.uuid4().hex[:4]}"

    # Verify model_id if given
    if payload.model_id:
        m = db.query(MLModel).filter(MLModel.id == payload.model_id).first()
        if not m:
            raise HTTPException(status_code=404, detail=f"Model ID {payload.model_id} tidak ditemukan.")

    new_ep = MLEndpoint(
        name=payload.name.strip(),
        slug=clean_slug,
        description=payload.description.strip() if payload.description else None,
        model_id=payload.model_id,
        is_active=payload.is_active,
        default_conf=payload.default_conf,
        default_iou=payload.default_iou,
        total_requests=0
    )
    db.add(new_ep)
    db.commit()
    db.refresh(new_ep)

    return {
        "success": True,
        "message": f"Serving endpoint '{new_ep.name}' berhasil dibuat!",
        "endpoint": {
            "id": new_ep.id,
            "name": new_ep.name,
            "slug": new_ep.slug,
            "predict_url": f"/api/v1/models/endpoints/{new_ep.slug}/predict",
            "model_id": new_ep.model_id
        }
    }


@router.put("/endpoints/{endpoint_id}")
def update_endpoint(endpoint_id: int, payload: EndpointUpdateRequest, db: Session = Depends(get_db)):
    """Update serving endpoint configuration."""
    ep = db.query(MLEndpoint).filter(MLEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint tidak ditemukan")

    if payload.name is not None and payload.name.strip():
        ep.name = payload.name.strip()
    if payload.slug is not None and payload.slug.strip():
        target_slug = slugify(payload.slug)
        duplicate = db.query(MLEndpoint).filter(MLEndpoint.slug == target_slug, MLEndpoint.id != endpoint_id).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="Slug endpoint sudah digunakan.")
        ep.slug = target_slug
    if payload.description is not None:
        ep.description = payload.description.strip()
    if payload.model_id is not None:
        m = db.query(MLModel).filter(MLModel.id == payload.model_id).first()
        if not m:
            raise HTTPException(status_code=404, detail=f"Model ID {payload.model_id} tidak ditemukan.")
        ep.model_id = payload.model_id
    if payload.is_active is not None:
        ep.is_active = payload.is_active
    if payload.default_conf is not None:
        ep.default_conf = payload.default_conf
    if payload.default_iou is not None:
        ep.default_iou = payload.default_iou

    db.commit()
    db.refresh(ep)

    return {
        "success": True,
        "message": f"Endpoint '{ep.name}' berhasil diperbarui.",
        "endpoint": {
            "id": ep.id,
            "name": ep.name,
            "slug": ep.slug,
            "model_id": ep.model_id,
            "is_active": ep.is_active
        }
    }


@router.put("/endpoints/{endpoint_id}/switch-model")
def switch_endpoint_model(endpoint_id: int, payload: EndpointSwitchModelRequest, db: Session = Depends(get_db)):
    """
    Instantly switch the target model connected to this endpoint.
    Clients calling the endpoint will immediately use the new model without URL change!
    """
    ep = db.query(MLEndpoint).filter(MLEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint tidak ditemukan")

    target_model = db.query(MLModel).filter(MLModel.id == payload.model_id).first()
    if not target_model:
        raise HTTPException(status_code=404, detail=f"Model ID {payload.model_id} tidak ditemukan di registry")

    old_model_id = ep.model_id
    ep.model_id = target_model.id
    db.commit()
    db.refresh(ep)

    return {
        "success": True,
        "message": f"Berhasil mengalihkan endpoint '{ep.name}' ke model '{target_model.name} ({target_model.version})'!",
        "endpoint_slug": ep.slug,
        "previous_model_id": old_model_id,
        "current_model": {
            "id": target_model.id,
            "name": target_model.name,
            "version": target_model.version,
            "framework": target_model.framework
        }
    }


@router.delete("/endpoints/{endpoint_id}")
def delete_endpoint(endpoint_id: int, db: Session = Depends(get_db)):
    """Delete a custom serving endpoint."""
    ep = db.query(MLEndpoint).filter(MLEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint tidak ditemukan")

    name = ep.name
    db.delete(ep)
    db.commit()
    return {"success": True, "message": f"Serving endpoint '{name}' berhasil dihapus."}


@router.post("/endpoints/{slug}/predict")
async def predict_via_endpoint(
    slug: str,
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    conf_threshold: Optional[float] = Form(None),
    iou_threshold: Optional[float] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Run detection inference specifically through the assigned endpoint and its connected model.
    """
    ep = db.query(MLEndpoint).filter(MLEndpoint.slug == slug).first()
    if not ep:
        raise HTTPException(status_code=404, detail=f"Serving endpoint '{slug}' tidak ditemukan")

    if not ep.is_active:
        raise HTTPException(status_code=403, detail=f"Serving endpoint '{slug}' sedang dinonaktifkan")

    # Image payload
    if file:
        image_bytes = await file.read()
        filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}.jpg"
    elif image_url:
        import requests
        try:
            resp = requests.get(image_url, timeout=10)
            resp.raise_for_status()
            image_bytes = resp.content
            filename = os.path.basename(image_url.split("?")[0]) or "remote_image.jpg"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Gagal mengambil gambar dari URL: {e}")
    else:
        raise HTTPException(status_code=400, detail="Wajib menyertakan file gambar atau image_url")

    # Threshold fallback to endpoint defaults
    c_thresh = conf_threshold if conf_threshold is not None else ep.default_conf
    i_thresh = iou_threshold if iou_threshold is not None else ep.default_iou

    # Run inference with endpoint's assigned model
    try:
        result = detection_service.predict(
            image_bytes,
            conf_threshold=c_thresh,
            iou_threshold=i_thresh,
            model_id=ep.model_id,
            db=db
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error pada endpoint '{slug}': {str(e)}")

    pred_id = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".jpg"

    raw_s3_key = f"datasets/raw/{pred_id}{ext}"
    orig_url = s3_service.upload_bytes(image_bytes, raw_s3_key, content_type="image/jpeg")

    annotated_s3_key = f"datasets/annotated/{pred_id}.jpg"
    annotated_url = s3_service.upload_bytes(result["annotated_bytes"], annotated_s3_key, content_type="image/jpeg")

    # Feedback logic with audit sampling
    import random
    initial_status = "pending"
    is_audit = False
    if result["top_confidence"] >= 0.88 and result["detection_count"] > 0:
        if random.random() < 0.10:
            initial_status = "audit_required"
            is_audit = True
        else:
            initial_status = "auto_labeled"

    # Store prediction record in DB with endpoint tag
    pred_record = MLPrediction(
        id=pred_id,
        model_id=result["model_id"],
        model_version=result["model_version"],
        endpoint_slug=ep.slug,
        original_image_url=orig_url,
        annotated_image_url=annotated_url,
        detections=json.dumps(result["detections"]),
        top_confidence=result["top_confidence"],
        detection_count=result["detection_count"],
        latency_ms=result["latency_ms"],
        feedback_status=initial_status,
        is_audit_sample=is_audit,
        image_quality=json.dumps(result.get("quality", {})),
        is_synced_to_ls=False
    )
    db.add(pred_record)

    # Update endpoint stats
    import datetime
    ep.total_requests = (ep.total_requests or 0) + 1
    ep.last_accessed_at = datetime.datetime.utcnow()

    db.commit()

    return {
        "prediction_id": pred_id,
        "endpoint": {
            "name": ep.name,
            "slug": ep.slug
        },
        "model_id": result["model_id"],
        "model_name": result["model_name"],
        "model_version": result["model_version"],
        "original_image_url": orig_url,
        "annotated_image_url": annotated_url,
        "detections": result["detections"],
        "detection_count": result["detection_count"],
        "top_confidence": result["top_confidence"],
        "latency_ms": result["latency_ms"],
        "image_width": result["image_width"],
        "image_height": result["image_height"],
        "quality": result.get("quality", {}),
        "feedback_status": initial_status,
        "is_audit_sample": is_audit
    }


@router.post("/endpoints/{slug}/predict-video")
async def predict_video_via_endpoint(
    slug: str,
    video: UploadFile = File(...),
    conf_threshold: Optional[float] = Form(None),
    iou_threshold: Optional[float] = Form(None),
    db: Session = Depends(get_db)
):
    """Run video inference specifically through the assigned endpoint and its connected model."""
    ep = db.query(MLEndpoint).filter(MLEndpoint.slug == slug).first()
    if not ep:
        raise HTTPException(status_code=404, detail=f"Serving endpoint '{slug}' tidak ditemukan")

    if not ep.is_active:
        raise HTTPException(status_code=403, detail=f"Serving endpoint '{slug}' sedang dinonaktifkan")

    video_bytes = await video.read()
    if not video_bytes:
        raise HTTPException(status_code=400, detail="File video kosong")

    c_thresh = conf_threshold if conf_threshold is not None else ep.default_conf
    i_thresh = iou_threshold if iou_threshold is not None else ep.default_iou

    import asyncio
    try:
        result = await asyncio.to_thread(
            detection_service.predict_video,
            video_bytes,
            conf_threshold=c_thresh,
            iou_threshold=i_thresh,
            model_id=ep.model_id,
            db=db
        )
        # Update endpoint stats
        import datetime
        ep.total_requests = (ep.total_requests or 0) + 1
        ep.last_accessed_at = datetime.datetime.utcnow()
        db.commit()

        return {
            "status": "success",
            "endpoint": {"name": ep.name, "slug": ep.slug},
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memproses video pada endpoint '{slug}': {str(e)}")
