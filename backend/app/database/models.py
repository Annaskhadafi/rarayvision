import uuid
import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.orm import relationship
try:
    from app.database.database import Base
except ImportError:
    from backend.app.database.database import Base

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



