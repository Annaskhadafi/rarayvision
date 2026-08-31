import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import sys
_CUR_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_CUR_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)
if _CUR_DIR not in sys.path:
    sys.path.insert(0, _CUR_DIR)

import cv2
cv2.setNumThreads(1)
try:
    import torch
    torch.set_num_threads(1)
except Exception:
    pass

import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse, FileResponse, Response, RedirectResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from starlette.exceptions import HTTPException as StarletteHTTPException
import socketio

from backend.app.controllers import auth_controller, api_key_controller, face_controller
from backend.app.controllers import hero_attendance_controller
from backend.app.services.socket_service import sio
from backend.app.database.database import Base, engine
from backend.app.database import models, rag_models, rag_datasource_models

# Try enabling pgvector extension if PostgreSQL
try:
    with engine.connect() as _conn:
        from sqlalchemy import text
        _conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        _conn.commit()
except Exception as _e:
    pass

# Create DB Tables
Base.metadata.create_all(bind=engine)

# Ensure embedding_v2 column exists in faces table
try:
    with engine.connect() as _conn:
        from sqlalchemy import text
        try:
            _conn.execute(text("ALTER TABLE faces ADD COLUMN embedding_v2 TEXT;"))
            _conn.commit()
            print("[DB] Added embedding_v2 column to faces table.")
        except Exception:
            pass
except Exception:
    pass

def create_default_admin():
    from backend.app.database.database import SessionLocal
    from backend.app.database.models import User
    from backend.app.core.security import get_password_hash
    
    db = SessionLocal()
    try:
        admin_email = os.getenv("RARAY_VISION_EMAIL", "admin@rarayvision.dfs.co.id")
        admin_password = os.getenv("RARAY_VISION_PASSWORD", "askingme")
        admin = db.query(User).filter(User.email == admin_email).first()
        if not admin:
            print(f"Creating default admin user: {admin_email}")
            admin = User(
                email=admin_email,
                password_hash=get_password_hash(admin_password),
                name="System Admin"
            )
            db.add(admin)
            db.commit()
            print(f"Default admin created successfully.")
        else:
            print(f"Admin user already exists: {admin_email}")
    except Exception as e:
        print(f"Failed to create default admin: {e}")
    finally:
        db.close()

create_default_admin()

fastapi_app = FastAPI(
    title="Raray Vision API",
    description="""
High-performance face recognition and computer vision API for face recognition,
liveness detection, face verification, and facial analysis.

Powered by:

\u2022 Buffalo-L (InsightFace)
\u2022 ArcFace (ResNet50)
\u2022 SCRFD Face Detection
\u2022 Custom ONNX Anti-Spoofing Model
\u2022 ONNX Runtime
\u2022 OpenCV
\u2022 NumPy
""",
    version="1.0.0",
    openapi_version="3.0.2",
    contact={"name": "Raray Vision Team", "url": "https://rarayvision.dfs.co.id"},
    docs_url=None,
    redoc_url=None,
)

# Mount Uploads directory
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
if not os.path.exists(uploads_dir):
    os.makedirs(uploads_dir)

@fastapi_app.get("/api/v1/uploads/{filename}")
def stream_upload_file(filename: str, request: Request):
    """
    HTTP Byte-Range Streaming endpoint (HTTP 206 Partial Content).
    Enables native HTML5 MP4 video streaming and seeking in Chrome, Edge, Safari, and Firefox.
    Falls back to S3 redirect if file is not stored on local disk.
    """
    file_path = os.path.join(uploads_dir, filename)
    if not os.path.exists(file_path):
        alt_path = os.path.join(os.path.dirname(__file__), "app", "uploads", filename)
        if os.path.exists(alt_path):
            file_path = alt_path
        else:
            # Fallback redirect to S3 Cloudhost Object Storage
            endpoint = os.getenv("OBJECT_STORAGE_ENDPOINT", "https://is3.cloudhost.id").rstrip('/')
            bucket = os.getenv("OBJECT_STORAGE_BUCKET", "onechitra")
            prefix = os.getenv("OBJECT_STORAGE_PREFIX", "upload")
            s3_url = f"{endpoint}/{bucket}/{prefix}/{filename}"
            return RedirectResponse(url=s3_url, status_code=302)

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")

    content_type = "video/mp4" if filename.endswith(".mp4") else "image/jpeg"
    if filename.endswith(".png"):
        content_type = "image/png"
    elif filename.endswith(".webp"):
        content_type = "image/webp"

    if range_header and filename.endswith(".mp4"):
        try:
            byte_str = range_header.replace("bytes=", "")
            start_str, end_str = byte_str.split("-") if "-" in byte_str else (byte_str, "")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1

            if start >= file_size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

            end = min(end, file_size - 1)
            chunk_size = (end - start) + 1

            def iterfile():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    bytes_left = chunk_size
                    while bytes_left > 0:
                        read_size = min(4096 * 16, bytes_left)
                        data = f.read(read_size)
                        if not data:
                            break
                        bytes_left -= len(data)
                        yield data

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Content-Type": content_type,
            }
            return StreamingResponse(iterfile(), status_code=206, headers=headers)
        except Exception as e:
            print(f"[Main] Range streaming fallback error: {e}")

    return FileResponse(file_path, media_type=content_type)

# Setup CORS
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# In development mode, allow all origins if ALLOWED_ORIGINS is not set
_env_mode = os.getenv("ENV", "development").lower()
if not _allowed_origins:
    if _env_mode == "production":
        import sys
        print("WARNING: ALLOWED_ORIGINS is not set in production. CORS will block all origins.", file=sys.stderr)
    else:
        _allowed_origins = ["*"]

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths to hide from Swagger UI & ReDoc
_HIDDEN_PATHS = {"/api/v1/faces/login"}

# HTTP middleware: intercept /openapi.json and strip hidden paths from response
@fastapi_app.middleware("http")
async def filter_openapi_schema(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/openapi.json":
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            schema = json.loads(body)
            paths = schema.get("paths", {})
            for path in _HIDDEN_PATHS:
                paths.pop(path, None)
            
            # Remove orphaned tag groups
            used_tags = {
                tag
                for methods in paths.values()
                for op in methods.values()
                if isinstance(op, dict)
                for tag in op.get("tags", [])
            }
            if "tags" in schema:
                schema["tags"] = [t for t in schema["tags"] if t.get("name") in used_tags]

            # FIX: Swagger UI 5.x needs 'format': 'binary' to render file upload buttons
            # even though OpenAPI 3.1.0 uses contentMediaType. We inject it here.
            schemas = schema.get("components", {}).get("schemas", {})
            for schema_name, schema_obj in schemas.items():
                if "properties" in schema_obj:
                    for prop_name, prop_data in schema_obj["properties"].items():
                        if prop_data.get("contentMediaType") == "application/octet-stream":
                            prop_data["format"] = "binary"

            return JSONResponse(content=schema, status_code=response.status_code)
        except Exception:
            return JSONResponse(content=json.loads(body), status_code=response.status_code)
    return response

from backend.app.controllers import auth_controller, api_key_controller, face_controller, tire_controller, inventory_controller, hse_controller, camera_controller, pdf_inspector_controller, anti_spoof_controller, anydoc_controller, rag_controller, rag_datasource_controller, automl_controller, fall_detection_controller

# Include Routers
fastapi_app.include_router(auth_controller.router)
fastapi_app.include_router(api_key_controller.router)
fastapi_app.include_router(face_controller.router)
fastapi_app.include_router(hero_attendance_controller.router)
fastapi_app.include_router(tire_controller.router)
fastapi_app.include_router(inventory_controller.router)
fastapi_app.include_router(hse_controller.router)
fastapi_app.include_router(fall_detection_controller.router)
fastapi_app.include_router(camera_controller.router)
fastapi_app.include_router(pdf_inspector_controller.router)
fastapi_app.include_router(anti_spoof_controller.router)
fastapi_app.include_router(anydoc_controller.router)
fastapi_app.include_router(rag_controller.router)
fastapi_app.include_router(rag_datasource_controller.router)
fastapi_app.include_router(automl_controller.router)

# Mount Tire Counter Sub-App directly onto /tire-api
try:
    _tire_dir = os.path.join(_PARENT_DIR, "warehouse-tire-counter")
    if _tire_dir not in sys.path:
        sys.path.insert(0, _tire_dir)
    from app import app as tire_counter_app
    fastapi_app.mount("/tire-api", tire_counter_app)
    print("[MainAPI] Successfully mounted /tire-api onto Vision API container.")
except Exception as e:
    print(f"[MainAPI] Warning: Could not mount tire-counter sub-app: {e}")


_FAVICON = "/api/v1/uploads/favicon.png"

# Custom Swagger UI — branded header with Raray Vision logo
@fastapi_app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    template_path = Path(__file__).parent / "templates" / "swagger.html"
    return HTMLResponse(template_path.read_text())

# Custom ReDoc — branded header with Raray Vision logo
@fastapi_app.get("/redoc", include_in_schema=False)
async def custom_redoc():
    template_path = Path(__file__).parent / "templates" / "redoc.html"
    return HTMLResponse(template_path.read_text())

def get_404_html():
    template_path = Path(__file__).parent / "templates" / "404.html"
    return template_path.read_text()

@fastapi_app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api"):
        return HTMLResponse(content=get_404_html(), status_code=404)
    return JSONResponse(content={"status": "error", "detail": exc.detail}, status_code=exc.status_code)

from pydantic import BaseModel

class FeedbackRequest(BaseModel):
    name: str
    email: str
    message: str

@fastapi_app.post("/api/v1/feedback", tags=["General"], include_in_schema=False)
def submit_feedback(feedback: FeedbackRequest):
    print(f"Feedback received from {feedback.name} ({feedback.email}): {feedback.message}")
    return {"status": "success", "message": "Feedback received"}

from sqlalchemy.orm import Session
from fastapi import Depends
from backend.app.database.database import get_db
from backend.app.database.models import Face, ApiKey, User
from backend.app.core.deps import get_current_user
from sqlalchemy.sql import func

@fastapi_app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "message": "Raray Vision API is online"}

@fastapi_app.get("/version", tags=["System"])
def get_version(current_user: User = Depends(get_current_user)):
    return {
        "version": "1.0.0",
        "model": "buffalo_l",
        "engine": "InsightFace"
    }

@fastapi_app.get("/stats", tags=["System"])
def get_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    registered_faces = db.query(func.count(Face.internal_id)).scalar() or 0
    total_requests = db.query(func.sum(ApiKey.usage_count)).scalar() or 0
    
    return {
        "registered_faces": registered_faces,
        "total_requests": int(total_requests),
        "today_requests": int(total_requests) # Placeholder for today
    }

# ── Daily Auto-Cleanup Scheduler ────────────────────────────────────────────
# Runs in a daemon thread: deletes chat sessions older than 7 days every 24h.
import threading

def _run_daily_chat_cleanup():
    import time
    # Wait 60s after startup before first run (let DB connections settle)
    time.sleep(60)
    while True:
        try:
            from backend.app.database.database import SessionLocal
            from backend.app.services.rag_service import RagService
            db = SessionLocal()
            try:
                result = RagService.cleanup_old_chat_sessions(db=db, days=7)
                print(
                    f"[AutoCleanup] Daily cleanup done: "
                    f"{result['deleted_sessions']} sessions, "
                    f"{result['deleted_facts']} auto-chat facts removed."
                )
            finally:
                db.close()
        except Exception as _cleanup_err:
            print(f"[AutoCleanup] Error during daily cleanup: {_cleanup_err}")
        # Sleep 24 hours before next run
        time.sleep(86400)

_cleanup_thread = threading.Thread(target=_run_daily_chat_cleanup, daemon=True, name="DailyRAGCleanup")
_cleanup_thread.start()
print("[AutoCleanup] Daily chat history cleanup scheduler started (retention: 7 days).")

# ── RAG Cache Pre-Warming Thread ─────────────────────────────────────────────
def _prewarm_rag_cache():
    import time
    time.sleep(2) # Give DB engine 2s to complete connection pool setup
    try:
        from backend.app.database.database import SessionLocal
        from backend.app.services.rag_service import RagService, get_fastembed_model, get_reranker_model
        # 1. Preload FastEmbed ONNX model in RAM
        get_fastembed_model()
        # 2. Preload Reranker model in RAM
        get_reranker_model()
        # 3. Preload chunk embeddings & memory facts into RAM
        db = SessionLocal()
        try:
            RagService._get_cached_chunks(db)
            RagService._get_cached_memory_facts(db)
            print("[RagWarmup] RAG in-memory chunk cache, FastEmbed engine, and Reranker pre-warmed successfully.")
        finally:
            db.close()
    except Exception as e:
        print(f"[RagWarmup] Warning: RAG prewarm error: {e}")

_warmup_thread = threading.Thread(target=_prewarm_rag_cache, daemon=True, name="RagWarmup")
_warmup_thread.start()
# ─────────────────────────────────────────────────────────────────────────────

# Setup Socket.IO App
app = socketio.ASGIApp(sio, fastapi_app)


