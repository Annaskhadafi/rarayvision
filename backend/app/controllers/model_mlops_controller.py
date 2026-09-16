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
    from backend.app.database.models import MLModel, MLPrediction
    from backend.app.services.detection_service import detection_service
    from backend.app.services.s3_service import s3_service
    from backend.app.services.label_studio_service import label_studio_service
    from backend.app.core.config import BASE_DIR
except ImportError:
    from app.database.database import get_db
    from app.database.models import MLModel, MLPrediction
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


@router.delete("/{model_id}")
def delete_model(model_id: int, db: Session = Depends(get_db)):
    """Delete a model from registry and filesystem."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if model.is_active:
        raise HTTPException(status_code=400, detail="Cannot delete the currently active model. Please activate another model first.")

    # Remove files
    try:
        if os.path.exists(model.model_path):
            os.remove(model.model_path)
        if model.evaluation_dir and os.path.exists(model.evaluation_dir):
            shutil.rmtree(model.evaluation_dir, ignore_errors=True)
    except Exception as e:
        print(f"[DeleteModel] File removal error: {e}")

    db.delete(model)
    db.commit()
    return {"success": True, "message": f"Model {model.name} deleted successfully"}


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
def get_production_analytics(db: Session = Depends(get_db)):
    """Get online production statistics: predictions, feedback ratio, and review queue."""
    total_preds = db.query(MLPrediction).count()
    good_count = db.query(MLPrediction).filter(MLPrediction.feedback_status == "good").count()
    bad_count = db.query(MLPrediction).filter(MLPrediction.feedback_status == "bad").count()
    auto_count = db.query(MLPrediction).filter(MLPrediction.feedback_status == "auto_labeled").count()
    audit_count = db.query(MLPrediction).filter(MLPrediction.feedback_status == "audit_required").count()
    pending_count = db.query(MLPrediction).filter(MLPrediction.feedback_status == "pending").count()

    unsynced_review_count = db.query(MLPrediction).filter(
        MLPrediction.feedback_status == "bad",
        MLPrediction.is_synced_to_ls == False
    ).count()

    unsynced_auto_count = db.query(MLPrediction).filter(
        MLPrediction.feedback_status.in_(["good", "auto_labeled"]),
        MLPrediction.is_synced_to_ls == False
    ).count()

    from sqlalchemy import func
    avg_lat = db.query(func.avg(MLPrediction.latency_ms)).scalar() or 0.0

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

    items = db.query(MLPrediction).filter(
        MLPrediction.feedback_status.in_(statuses_to_sync),
        MLPrediction.is_synced_to_ls == False
    ).limit(200).all()

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

    zip_bytes = await images_zip_file.read()
    zip_stream = io.BytesIO(zip_bytes)

    image_url_mapping = {}
    uploaded_files = []

    endpoint, bucket, _, region, _, _ = get_s3_credentials()

    try:
        with zipfile.ZipFile(zip_stream, "r") as zf:
            for member in zf.namelist():
                fname = os.path.basename(member)
                if not fname or member.endswith("/"):
                    continue
                file_bytes = zf.read(member)
                s3_key = f"{s3_folder_prefix}/{fname}"
                accessible_url = s3_service.upload_bytes(file_bytes, s3_key)
                image_url_mapping[fname] = accessible_url
                uploaded_files.append(fname)

        # Convert COCO annotations to Label Studio format
        tasks = label_studio_service.convert_coco_to_label_studio(coco_json, image_url_mapping)

        # Also save tasks.json in S3 folder for direct import in Label Studio
        tasks_json_bytes = json.dumps(tasks, indent=2).encode("utf-8")
        tasks_s3_key = f"datasets/{folder_name}/label_studio_tasks.json"
        tasks_url = s3_service.upload_bytes(tasks_json_bytes, tasks_s3_key, content_type="application/json")

        # Optionally push directly if Label Studio instance is configured
        ls_push_result = None
        if project_id:
            ls_push_result = label_studio_service.push_bulk_tasks(tasks, project_id=project_id)

        s3_uri = f"s3://{bucket}/{s3_folder_prefix}/"

        return {
            "success": True,
            "dataset_folder": folder_name,
            "s3_bucket": bucket,
            "s3_folder_prefix": f"{s3_folder_prefix}/",
            "s3_uri": s3_uri,
            "s3_endpoint": endpoint,
            "tasks_json_url": tasks_url,
            "images_uploaded_count": len(uploaded_files),
            "tasks_created_count": len(tasks),
            "categories": [c.get("name") for c in coco_json.get("categories", [])],
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
            "message": f"Dataset berhasil diunggah ke folder S3 '{folder_name}'. URL dan prefix siap di-copy ke Label Studio."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengimpor dataset: {str(e)}")


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
