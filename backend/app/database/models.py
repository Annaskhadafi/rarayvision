import uuid
import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
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

