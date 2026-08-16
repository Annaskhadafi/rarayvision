import sys
import os

_CUR_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_CUR_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)
if _CUR_DIR not in sys.path:
    sys.path.insert(0, _CUR_DIR)

import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse, FileResponse, Response
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from starlette.exceptions import HTTPException as StarletteHTTPException
import socketio

from backend.app.controllers import auth_controller, api_key_controller, face_controller
from backend.app.controllers import hero_attendance_controller
from backend.app.services.socket_service import sio
from backend.app.database.database import Base, engine

# Create DB Tables
Base.metadata.create_all(bind=engine)

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
    """
    file_path = os.path.join(uploads_dir, filename)
    if not os.path.exists(file_path):
        raise StarletteHTTPException(status_code=404, detail="File not found")

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

from backend.app.controllers import auth_controller, api_key_controller, face_controller, tire_controller, inventory_controller, hse_controller, camera_controller, pdf_inspector_controller, anti_spoof_controller

# Include Routers
fastapi_app.include_router(auth_controller.router)
fastapi_app.include_router(api_key_controller.router)
fastapi_app.include_router(face_controller.router)
fastapi_app.include_router(hero_attendance_controller.router)
fastapi_app.include_router(tire_controller.router)
fastapi_app.include_router(inventory_controller.router)
fastapi_app.include_router(hse_controller.router)
fastapi_app.include_router(camera_controller.router)
fastapi_app.include_router(pdf_inspector_controller.router)
fastapi_app.include_router(anti_spoof_controller.router)


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
    if exc.status_code == 404:
        return HTMLResponse(content=get_404_html(), status_code=404)
    return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)

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

# Setup Socket.IO App
app = socketio.ASGIApp(sio, fastapi_app)


