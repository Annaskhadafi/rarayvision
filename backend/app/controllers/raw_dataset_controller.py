import asyncio
import json
import mimetypes
import os
import re
import threading
import uuid
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

try:
    from backend.app.core.deps import get_current_user
    from backend.app.database.database import get_db
    from backend.app.database.models import DatasetStorageConfig, RawDataset, RawDatasetFile, RawDatasetImportBatch, User
    from backend.app.services.dataset_storage_service import DatasetStorageError, DatasetStorageService
except ImportError:
    from app.core.deps import get_current_user
    from app.database.database import get_db
    from app.database.models import DatasetStorageConfig, RawDataset, RawDatasetFile, RawDatasetImportBatch, User
    from app.services.dataset_storage_service import DatasetStorageError, DatasetStorageService

router = APIRouter(prefix="/api/v1/datasets", tags=["Raw Dataset Storage"])
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "https://vision.chitraparatama.com").rstrip("/")
_storage_config_lock = threading.Lock()
_LABEL_STUDIO_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}


class StorageConfigRequest(BaseModel):
    endpoint_url: Optional[str] = None
    bucket: Optional[str] = None
    region: Optional[str] = None
    prefix: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None

    @validator("endpoint_url")
    def validate_endpoint(cls, value):
        if value is None:
            return value
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("Endpoint harus diawali http:// atau https://.")
        return value


class DatasetNameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)


class FileNameRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)


class LabelStudioImportRequest(BaseModel):
    batch_id: Optional[str] = None
    file_ids: Optional[List[str]] = None


def _clean_prefix(value: Optional[str]) -> str:
    return "/".join(part for part in (value or "datasets").strip().split("/") if part)


def _config_values(config: DatasetStorageConfig):
    return {
        "endpoint_url": config.endpoint_url,
        "bucket": config.bucket,
        "region": config.region,
        "prefix": config.prefix,
        "access_key_id": config.access_key_id,
        "secret_access_key": config.secret_access_key,
    }


def _masked(value: str):
    if not value:
        return ""
    return value[:4] + "..." + value[-4:] if len(value) > 8 else "••••••••"


def _config_payload(config: Optional[DatasetStorageConfig]):
    if not config:
        return {
            "configured": False,
            "endpoint_url": "",
            "bucket": "",
            "region": "us-east-1",
            "prefix": "datasets",
            "access_key_id": "",
            "secret_access_key_configured": False,
        }
    return {
        "configured": True,
        "endpoint_url": config.endpoint_url,
        "bucket": config.bucket,
        "region": config.region,
        "prefix": config.prefix,
        "access_key_id": _masked(config.access_key_id),
        "secret_access_key_configured": bool(config.secret_access_key),
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


def _get_service(db: Session, payload: Optional[StorageConfigRequest] = None):
    saved = db.query(DatasetStorageConfig).filter(DatasetStorageConfig.id == 1).first()
    values = _config_values(saved) if saved else {}
    if payload:
        for key, value in payload.dict(exclude_unset=True).items():
            if value not in (None, ""):
                values[key] = value
    values["prefix"] = _clean_prefix(values.get("prefix"))
    try:
        return DatasetStorageService(values)
    except DatasetStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_dataset_service(dataset: RawDataset):
    try:
        return DatasetStorageService({
            "endpoint_url": dataset.storage_endpoint_url,
            "bucket": dataset.storage_bucket,
            "region": dataset.storage_region,
            "access_key_id": dataset.storage_access_key_id,
            "secret_access_key": dataset.storage_secret_access_key,
        })
    except DatasetStorageError as exc:
        raise HTTPException(status_code=400, detail="Konfigurasi storage dataset ini tidak lengkap.") from exc


def _dataset_url(dataset_id: str, pending=False):
    suffix = "label-studio-pending.json" if pending else "label-studio.json"
    return f"{PUBLIC_APP_URL}/api/v1/datasets/raw/{dataset_id}/{suffix}"


def _pending_dataset_url(dataset_id: str, batch_id: str):
    query = urlencode({"batch_id": batch_id})
    return f"{_dataset_url(dataset_id, pending=True)}?{query}"


def _file_url(file_id: str):
    return f"{PUBLIC_APP_URL}/api/v1/datasets/raw/files/{file_id}/content"


def _file_payload(item: RawDatasetFile):
    return {
        "id": item.id,
        "status": item.status,
        "filename": item.filename,
        "content_type": item.content_type,
        "size_bytes": item.size_bytes,
        "label_studio_imported_at": item.label_studio_imported_at.isoformat() if item.label_studio_imported_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "url": _file_url(item.id),
    }


def _dataset_payload(item: RawDataset, include_files=False):
    result = {
        "id": item.id,
        "name": item.name,
        "folder": item.folder,
        "status": item.status,
        "file_count": item.file_count,
        "total_bytes": item.total_bytes,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "last_uploaded_at": item.last_uploaded_at.isoformat() if item.last_uploaded_at else None,
        "label_studio_import_url": _dataset_url(item.id),
        "label_studio_pending_import_url": _dataset_url(item.id, pending=True),
        "pending_file_count": sum(1 for file in item.files if file.status == "active" and not file.label_studio_imported_at and file.content_type.lower() in _LABEL_STUDIO_IMAGE_TYPES),
        "imported_file_count": sum(1 for file in item.files if file.status == "active" and file.label_studio_imported_at and file.content_type.lower() in _LABEL_STUDIO_IMAGE_TYPES),
    }
    if include_files:
        result["files"] = [_file_payload(file) for file in sorted(item.files, key=lambda row: row.created_at or datetime.min, reverse=True)]
    return result


def _safe_filename(value: str):
    filename = os.path.basename((value or "").replace("\\", "/")).strip()
    filename = re.sub(r"[^a-zA-Z0-9._() -]", "_", filename)
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="Nama file tidak valid.")
    return filename[:255]


def _require_storage_admin(user: User):
    admin_email = os.getenv("RARAY_VISION_EMAIL", "admin@rarayvision.dfs.co.id").strip()
    if not admin_email or (user.email or "") != admin_email:
        raise HTTPException(status_code=403, detail="Hanya admin storage yang boleh mengubah konfigurasi S3.")
    return user


def require_storage_admin(user: User = Depends(get_current_user)):
    return _require_storage_admin(user)


@router.get("/storage/config")
def get_storage_config(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    config = db.query(DatasetStorageConfig).filter(DatasetStorageConfig.id == 1).first()
    return _config_payload(config)


@router.put("/storage/config")
def save_storage_config(payload: StorageConfigRequest, db: Session = Depends(get_db), _user: User = Depends(require_storage_admin)):
    with _storage_config_lock:
        return _save_storage_config(payload, db)


def _save_storage_config(payload: StorageConfigRequest, db: Session):
    config = db.query(DatasetStorageConfig).filter(DatasetStorageConfig.id == 1).first()
    values = _config_values(config) if config else {}
    for key, value in payload.dict(exclude_unset=True).items():
        if value not in (None, ""):
            values[key] = value
    missing = [key for key in ("endpoint_url", "bucket", "access_key_id", "secret_access_key") if not values.get(key)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Field S3 wajib diisi: {', '.join(missing)}")
    values["prefix"] = _clean_prefix(values.get("prefix"))
    try:
        DatasetStorageService(values)
    except DatasetStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not config:
        config = DatasetStorageConfig(id=1)
        db.add(config)
    for key, value in values.items():
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
    return {"success": True, "config": _config_payload(config)}


@router.post("/storage/test")
def test_storage_config(payload: Optional[StorageConfigRequest] = None, db: Session = Depends(get_db), _user: User = Depends(require_storage_admin)):
    service = _get_service(db, payload)
    try:
        service.test_connection()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Koneksi S3 gagal: {exc}") from exc
    return {"success": True, "message": "Koneksi S3 dataset berhasil diuji."}


@router.post("/raw", status_code=201)
def create_raw_dataset(payload: DatasetNameRequest, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    with _storage_config_lock:
        return _create_raw_dataset(payload, db)


def _create_raw_dataset(payload: DatasetNameRequest, db: Session):
    clean_name = payload.name.strip()
    _get_service(db)
    config = db.query(DatasetStorageConfig).filter(DatasetStorageConfig.id == 1).first()
    dataset_id = str(uuid.uuid4())
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean_name).strip("-").lower() or "dataset"
    folder = f"{_clean_prefix(config.prefix)}/raw/{slug}-{dataset_id[:8]}"
    dataset = RawDataset(
        id=dataset_id,
        name=clean_name,
        folder=folder,
        storage_endpoint_url=config.endpoint_url,
        storage_bucket=config.bucket,
        storage_region=config.region,
        storage_access_key_id=config.access_key_id,
        storage_secret_access_key=config.secret_access_key,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return _dataset_payload(dataset, include_files=True)


@router.get("/raw")
def list_raw_datasets(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    rows = db.query(RawDataset).order_by(RawDataset.updated_at.desc(), RawDataset.created_at.desc()).all()
    return {"datasets": [_dataset_payload(item) for item in rows]}


@router.get("/raw/{dataset_id}")
def get_raw_dataset(dataset_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    dataset = db.query(RawDataset).filter(RawDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Raw dataset tidak ditemukan.")
    return _dataset_payload(dataset, include_files=True)


@router.patch("/raw/{dataset_id}")
def rename_raw_dataset(dataset_id: str, payload: DatasetNameRequest, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    dataset = db.query(RawDataset).filter(RawDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Raw dataset tidak ditemukan.")
    dataset.name = payload.name.strip()
    db.commit()
    db.refresh(dataset)
    return _dataset_payload(dataset)


@router.post("/raw/{dataset_id}/files")
async def upload_raw_files(dataset_id: str, files: List[UploadFile] = File(...), db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    dataset = db.query(RawDataset).filter(RawDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Raw dataset tidak ditemukan.")
    if dataset.status != "active":
        raise HTTPException(status_code=409, detail="Dataset sedang diproses untuk dihapus; upload baru ditolak.")
    service = _get_dataset_service(dataset)
    uploaded = []
    uploaded_keys = []
    try:
        for incoming in files:
            filename = _safe_filename(incoming.filename or "")
            content_type = incoming.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            await incoming.seek(0)
            size = int(incoming.size or 0)
            if not size:
                incoming.file.seek(0, os.SEEK_END)
                size = incoming.file.tell()
                await incoming.seek(0)
            key = f"{dataset.folder}/{uuid.uuid4().hex[:12]}-{filename}"
            await asyncio.to_thread(service.upload_fileobj, incoming.file, key, content_type, size)
            uploaded_keys.append(key)
            uploaded.append(RawDatasetFile(dataset_id=dataset.id, filename=filename, s3_key=key, content_type=content_type, size_bytes=size))
        for item in uploaded:
            db.add(item)
        updated = db.query(RawDataset).filter(RawDataset.id == dataset.id, RawDataset.status == "active").update({
            RawDataset.file_count: RawDataset.file_count + len(uploaded),
            RawDataset.total_bytes: RawDataset.total_bytes + sum(item.size_bytes for item in uploaded),
            RawDataset.last_uploaded_at: datetime.utcnow(),
        }, synchronize_session=False)
        if updated != 1:
            raise RuntimeError("Dataset berubah status saat upload berlangsung; object dibersihkan ulang.")
        db.commit()
    except Exception as exc:
        db.rollback()
        for key in uploaded_keys:
            try:
                service.delete_key(key)
            except Exception:
                pass
        raise HTTPException(status_code=502, detail=f"Upload ke S3 gagal: {exc}") from exc
    try:
        for item in uploaded:
            db.refresh(item)
        db.refresh(dataset)
    except Exception:
        pass
    return {"success": True, "files": [_file_payload(item) for item in uploaded], "dataset": _dataset_payload(dataset, include_files=True)}


@router.patch("/raw/{dataset_id}/files/{file_id}")
def rename_raw_file(dataset_id: str, file_id: str, payload: FileNameRequest, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    dataset = db.query(RawDataset).filter(RawDataset.id == dataset_id).first()
    item = db.query(RawDatasetFile).filter(RawDatasetFile.id == file_id, RawDatasetFile.dataset_id == dataset_id).first()
    if not dataset or not item:
        raise HTTPException(status_code=404, detail="File tidak ditemukan.")
    filename = _safe_filename(payload.filename)
    item.filename = filename
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return {"success": True, "file": _file_payload(item)}


@router.delete("/raw/{dataset_id}/files/{file_id}")
def delete_raw_file(dataset_id: str, file_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    dataset = db.query(RawDataset).with_for_update().filter(RawDataset.id == dataset_id).first()
    item = db.query(RawDatasetFile).filter(RawDatasetFile.id == file_id, RawDatasetFile.dataset_id == dataset_id).first()
    if not dataset or not item:
        raise HTTPException(status_code=404, detail="File tidak ditemukan.")
    service = _get_dataset_service(dataset)
    key = item.s3_key
    item.status = "deleting"
    db.commit()
    try:
        service.delete_key(key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"File gagal dihapus dari S3: {exc}") from exc
    dataset = db.query(RawDataset).with_for_update().filter(RawDataset.id == dataset_id).first()
    item = db.query(RawDatasetFile).filter(RawDatasetFile.id == file_id, RawDatasetFile.dataset_id == dataset_id).first()
    if not dataset or not item:
        return {"success": True}
    dataset.file_count = max(0, (dataset.file_count or 0) - 1)
    dataset.total_bytes = max(0, (dataset.total_bytes or 0) - (item.size_bytes or 0))
    db.delete(item)
    db.commit()
    return {"success": True}


@router.delete("/raw/{dataset_id}")
def delete_raw_dataset(dataset_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    dataset = db.query(RawDataset).with_for_update().filter(RawDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Raw dataset tidak ditemukan.")
    service = _get_dataset_service(dataset)
    keys = [item.s3_key for item in dataset.files]
    dataset.status = "deleting"
    db.commit()
    try:
        for key in keys:
            service.delete_key(key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Dataset belum dihapus; object S3 gagal dibersihkan: {exc}") from exc
    db.delete(dataset)
    db.commit()
    return {"success": True}


@router.get("/raw/files/{file_id}/content")
def stream_raw_file(file_id: str, db: Session = Depends(get_db)):
    item = db.query(RawDatasetFile).filter(RawDatasetFile.id == file_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="File tidak ditemukan.")
    try:
        body = _get_dataset_service(item.dataset).get_object(item.s3_key)["Body"]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"File S3 tidak dapat dibaca: {exc}") from exc

    def iterator():
        try:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    safe_inline_types = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
    disposition = "inline" if item.content_type.lower() in safe_inline_types else "attachment"
    return StreamingResponse(
        iterator(),
        media_type=item.content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{item.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.get("/raw/{dataset_id}/label-studio.json")
def label_studio_tasks(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(RawDataset).filter(RawDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Raw dataset tidak ditemukan.")
    return _label_studio_tasks(dataset)


def _label_studio_tasks(dataset, pending=False, file_ids=None):
    selected_ids = set(file_ids or [])
    return [
        {"data": {"image": _file_url(item.id), "original_filename": item.filename, "dataset": dataset.name, "external_id": item.id}}
        for item in dataset.files
        if dataset.status == "active"
        and item.status == "active"
        and (not pending or not item.label_studio_imported_at)
        and (not selected_ids or item.id in selected_ids)
        and item.content_type.lower() in _LABEL_STUDIO_IMAGE_TYPES
    ]


@router.get("/raw/{dataset_id}/label-studio-pending.json")
def label_studio_pending_tasks(dataset_id: str, batch_id: Optional[str] = None, db: Session = Depends(get_db)):
    dataset = db.query(RawDataset).filter(RawDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Raw dataset tidak ditemukan.")
    selected_ids = None
    if batch_id:
        batch = db.query(RawDatasetImportBatch).filter(RawDatasetImportBatch.id == batch_id, RawDatasetImportBatch.dataset_id == dataset_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Snapshot import tidak ditemukan.")
        selected_ids = json.loads(batch.file_ids)
    return _label_studio_tasks(dataset, pending=True, file_ids=selected_ids or None)


@router.post("/raw/{dataset_id}/label-studio/prepare")
def prepare_label_studio_import(dataset_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    dataset = db.query(RawDataset).filter(RawDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Raw dataset tidak ditemukan.")
    file_ids = [
        item.id for item in dataset.files
        if item.status == "active" and not item.label_studio_imported_at and item.content_type.lower() in _LABEL_STUDIO_IMAGE_TYPES
    ]
    if not file_ids:
        raise HTTPException(status_code=409, detail="Tidak ada file baru yang siap di-import.")
    batch = RawDatasetImportBatch(dataset_id=dataset.id, file_ids=json.dumps(file_ids))
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return {"success": True, "batch_id": batch.id, "file_ids": file_ids, "url": _pending_dataset_url(dataset.id, batch.id)}


@router.post("/raw/{dataset_id}/label-studio/mark-imported")
def mark_label_studio_imported(dataset_id: str, payload: LabelStudioImportRequest, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    dataset = db.query(RawDataset).filter(RawDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Raw dataset tidak ditemukan.")
    batch = None
    if payload.batch_id:
        batch = db.query(RawDatasetImportBatch).filter(RawDatasetImportBatch.id == payload.batch_id, RawDatasetImportBatch.dataset_id == dataset_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Snapshot import tidak ditemukan.")
        file_ids = json.loads(batch.file_ids)
    else:
        file_ids = payload.file_ids or []
    file_ids = list(dict.fromkeys(file_ids))
    if not file_ids:
        raise HTTPException(status_code=400, detail="Snapshot import kosong.")
    files = db.query(RawDatasetFile).filter(
        RawDatasetFile.dataset_id == dataset_id,
        RawDatasetFile.id.in_(file_ids),
        RawDatasetFile.status == "active",
    ).all()
    if len(files) != len(file_ids) or any(item.content_type.lower() not in _LABEL_STUDIO_IMAGE_TYPES for item in files):
        raise HTTPException(status_code=400, detail="Satu atau lebih file tidak ditemukan di dataset ini.")
    imported_at = datetime.utcnow()
    for item in files:
        item.label_studio_imported_at = imported_at
    if batch:
        batch.imported_at = imported_at
    db.commit()
    db.refresh(dataset)
    return {"success": True, "dataset": _dataset_payload(dataset, include_files=True)}
