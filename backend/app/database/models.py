import uuid
import datetime
from sqlalchemy import BigInteger, Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.orm import relationship
try:
    from backend.app.database.database import Base
except ImportError:
    from app.database.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    password_hash = Column(String(255), nullable=True)
    store_images = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    faces = relationship("Face", back_populates="user", cascade="all, delete-orphan")
    tire_scans = relationship("TireScan", back_populates="user", cascade="all, delete-orphan")

class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key_string = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    status = Column(String(50), default="Active")
    expires_at = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="api_keys")

class Face(Base):
    __tablename__ = "faces"

    internal_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    face_id = Column(String(100), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    embedding = Column(Text, nullable=False)
    embedding_v2 = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="faces")

class TireScan(Base):
    __tablename__ = "tire_scans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    serial_number = Column(String(255), index=True, nullable=True)
    dot_code = Column(String(100), index=True, nullable=True)
    manufacturer = Column(String(255), nullable=True)
    model_name = Column(String(255), nullable=True)
    size = Column(String(255), nullable=True)
    load_speed = Column(String(100), nullable=True)
    special_markings = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    confidence = Column(String(50), default="0.95")
    mode = Column(String(50), default="pipeline")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="tire_scans")

class CVConfig(Base):
    """Menyimpan konfigurasi aktif per modul (inventory / hse)"""
    __tablename__ = "cv_configs"

    id = Column(Integer, primary_key=True, index=True)
    module = Column(String(50), index=True, nullable=False)   # "inventory" | "hse"
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    model_name = Column(String(100), default="yolov8n")
    confidence = Column(Float, default=0.5)
    iou_threshold = Column(Float, default=0.45)
    target_classes = Column(Text, default="[]")         # JSON string e.g. ["box","pallet"]
    extra_params = Column(Text, default="{}")           # JSON string for extra settings
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class STTConfig(Base):
    """Single active CPU speech-to-text configuration."""
    __tablename__ = "stt_configs"

    id = Column(Integer, primary_key=True, index=True)
    active_model = Column(String(100), nullable=False, default="fw-base-int8")
    language = Column(String(10), nullable=False, default="id")
    cpu_threads = Column(Integer, nullable=False, default=2)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class HSEZoneConfig(Base):
    """Menyimpan definisi Polygon Zone untuk HSE"""
    __tablename__ = "hse_zone_configs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    zone_name = Column(String(100), nullable=False)
    zone_type = Column(String(50), default="danger")   # "danger" | "warning" | "safe"
    polygon_points = Column(Text, nullable=False)      # JSON: [[x,y],[x,y],...]
    camera_id = Column(String(100), default="default")
    color_hex = Column(String(10), default="#FF0000")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class InventoryScan(Base):
    """Log hasil scan inventory"""
    __tablename__ = "inventory_scans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    api_key_id = Column(String(36), nullable=True)
    scan_type = Column(String(50), nullable=False)   # "count_boxes" | "defect_check" | "shelf_occupancy"
    image_url = Column(String(500), nullable=True)
    result_image_url = Column(String(500), nullable=True)
    result_json = Column(Text, nullable=True)
    total_count = Column(Integer, default=0)
    model_used = Column(String(100), default="yolov8n")
    confidence_used = Column(Float, default=0.5)
    processing_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class HSEIncident(Base):
    """Log incident / near-miss K3"""
    __tablename__ = "hse_incidents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    api_key_id = Column(String(36), nullable=True)
    incident_type = Column(String(50), nullable=False)   # "ppe_violation" | "danger_zone" | "near_miss"
    severity = Column(String(20), default="MEDIUM")       # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    zone_id = Column(String(36), nullable=True)
    image_url = Column(String(500), nullable=True)
    result_image_url = Column(String(500), nullable=True)
    result_json = Column(Text, nullable=True)
    persons_count = Column(Integer, default=0)
    violations_count = Column(Integer, default=0)
    model_used = Column(String(100), default="yolov8n")
    processing_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class HSEPPERule(Base):
    """Konfigurasi aturan APD yang wajib dipakai"""
    __tablename__ = "hse_ppe_rules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rule_name = Column(String(100), nullable=False, default="Standard Warehouse PPE")
    require_helmet = Column(Boolean, default=True)
    require_vest = Column(Boolean, default=True)
    require_mask = Column(Boolean, default=False)
    require_gloves = Column(Boolean, default=False)
    require_boots = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class Camera(Base):
    """Menyimpan data konfigurasi CCTV / IP Camera"""
    __tablename__ = "cameras"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String(100), nullable=False)               # e.g. "CCTV Gudang Rak A"
    stream_url = Column(String(500), nullable=False)         # e.g. "rtsp://..." or "http://..."
    location = Column(String(200), default="Main Facility")  # e.g. "Gudang Utama", "Area Pabrik"
    camera_type = Column(String(50), default="rtsp")         # "rtsp" | "http" | "webcam"
    preset_brand = Column(String(50), default="generic")     # "hikvision" | "dahua" | "uniview" | "generic"
    enable_ai_overlay = Column(Boolean, default=True)        # Active AI annotation on live stream
    ai_module = Column(String(50), default="hse")            # "hse" | "inventory" | "none"
    status = Column(String(20), default="OFFLINE")           # "ONLINE" | "OFFLINE"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)





class MLModel(Base):
    """Menyimpan registry model machine learning (YOLO, ONNX) dengan versioning & status aktif"""
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    version = Column(String(50), nullable=False)
    task_type = Column(String(50), default="detection")
    framework = Column(String(50), default="yolo")
    model_path = Column(String(500), nullable=False)
    onnx_path = Column(String(500), nullable=True)
    classes = Column(Text, nullable=True) # JSON list of class names
    is_active = Column(Boolean, default=False)
    description = Column(String(255), nullable=True)
    metrics_summary = Column(Text, nullable=True) # JSON summary (mAP50, precision, recall)
    evaluation_dir = Column(String(500), nullable=True) # Directory storing confusion matrix, curves, etc.
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class MLPrediction(Base):
    """Mencatat setiap prediksi inferensi, gambar di S3, dan data flywheel feedback"""
    __tablename__ = "ml_predictions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_id = Column(Integer, ForeignKey("ml_models.id", ondelete="SET NULL"), nullable=True)
    model_version = Column(String(50), nullable=True)
    endpoint_slug = Column(String(80), nullable=True, index=True) # Tag serving endpoint
    original_image_url = Column(String(500), nullable=False)
    annotated_image_url = Column(String(500), nullable=True)
    detections = Column(Text, nullable=True) # JSON list of boxes and labels
    top_confidence = Column(Float, default=0.0)
    detection_count = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    feedback_status = Column(String(30), default="pending") # pending, good, bad, auto_labeled
    feedback_notes = Column(Text, nullable=True)
    is_audit_sample = Column(Boolean, default=False)
    image_quality = Column(Text, nullable=True)
    is_synced_to_ls = Column(Boolean, default=False)
    label_studio_task_id = Column(Integer, nullable=True)
    # Human corrections are kept separately from model detections.  The model
    # output remains available for audit/retraining comparisons.
    corrected_annotations = Column(Text, nullable=True)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    feedback_source = Column(String(80), nullable=True)
    feedback_source_record_id = Column(String(160), nullable=True)
    feedback_actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    feedback_actor_email = Column(String(255), nullable=True)
    feedback_idempotency_key = Column(String(255), nullable=True, index=True)
    feedback_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class MLEndpoint(Base):
    """Menyimpan konfigurasi custom serving endpoint untuk melayani model tertentu secara independen"""
    __tablename__ = "ml_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False) # e.g. "CCTV APD Area Gudang"
    slug = Column(String(80), unique=True, nullable=False, index=True) # e.g. "cctv-apd"
    description = Column(String(255), nullable=True)
    model_id = Column(Integer, ForeignKey("ml_models.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)
    default_conf = Column(Float, default=0.25)
    default_iou = Column(Float, default=0.45)
    total_requests = Column(Integer, default=0)
    last_accessed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class MLDataset(Base):
    """Dataset archive imported through Data Studio, including reusable artifact links."""
    __tablename__ = "ml_datasets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(160), nullable=False)
    folder = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(String(30), default="ready", nullable=False)
    image_count = Column(Integer, default=0)
    task_count = Column(Integer, default=0)
    categories = Column(Text, default="[]")
    images = Column(Text, default="[]")
    artifacts = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class DatasetStorageConfig(Base):
    """Dedicated S3-compatible storage settings for raw datasets."""
    __tablename__ = "dataset_storage_configs"

    id = Column(Integer, primary_key=True, default=1)
    endpoint_url = Column(String(500), nullable=False)
    bucket = Column(String(255), nullable=False)
    region = Column(String(100), nullable=False, default="us-east-1")
    prefix = Column(String(500), nullable=False, default="datasets")
    access_key_id = Column(String(255), nullable=False)
    secret_access_key = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class RawDataset(Base):
    """A named raw dataset workspace backed by the dedicated dataset bucket."""
    __tablename__ = "raw_datasets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(160), nullable=False)
    folder = Column(String(500), unique=True, nullable=False, index=True)
    status = Column(String(30), default="active", nullable=False)
    storage_endpoint_url = Column(String(500), nullable=False)
    storage_bucket = Column(String(255), nullable=False)
    storage_region = Column(String(100), nullable=False)
    storage_access_key_id = Column(String(255), nullable=False)
    storage_secret_access_key = Column(String(500), nullable=False)
    file_count = Column(Integer, default=0, nullable=False)
    total_bytes = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    last_uploaded_at = Column(DateTime, nullable=True)

    files = relationship("RawDatasetFile", back_populates="dataset", cascade="all, delete-orphan")
    import_batches = relationship("RawDatasetImportBatch", cascade="all, delete-orphan")


class RawDatasetFile(Base):
    """Metadata for one object in a raw dataset."""
    __tablename__ = "raw_dataset_files"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_id = Column(String(36), ForeignKey("raw_datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(30), default="active", nullable=False)
    filename = Column(String(255), nullable=False)
    s3_key = Column(String(1000), unique=True, nullable=False)
    content_type = Column(String(150), nullable=False, default="application/octet-stream")
    size_bytes = Column(BigInteger, default=0, nullable=False)
    label_studio_imported_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    dataset = relationship("RawDataset", back_populates="files")


class RawDatasetImportBatch(Base):
    """Frozen file IDs used by one Label Studio import URL."""
    __tablename__ = "raw_dataset_import_batches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_id = Column(String(36), ForeignKey("raw_datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    file_ids = Column(Text, nullable=False)
    imported_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
