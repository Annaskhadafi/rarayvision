from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy.orm import Session
from backend.app.schemas.schemas import RegisterRequest, LoginRequest, UpdateProfileRequest, UpdatePasswordRequest, EditUserRequest
from backend.app.core.security import get_password_hash, verify_password, create_access_token
from backend.app.core.deps import get_current_user
from backend.app.database import database as db
from backend.app.database import models as db_models
from backend.app.services.ml_service import process_global_face_login, thread_pool
import asyncio
import cv2
import numpy as np

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.get("/registered-users", include_in_schema=False)
def get_registered_users(db_session: Session = Depends(db.get_db)):
    users = db_session.query(db_models.User).order_by(db_models.User.created_at.desc()).all()
    return {
        "status": "success",
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name or u.email.split("@")[0],
                "avatar_url": u.avatar_url,
                "has_face": len(u.faces) > 0 if u.faces else False,
                "created_at": u.created_at.isoformat() if u.created_at else None
            }
            for u in users
        ]
    }

@router.get("/me", include_in_schema=False)
def get_me(current_user: db_models.User = Depends(get_current_user)):
    return {
        "status": "success",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name or "",
            "avatar_url": current_user.avatar_url,
            "has_password": current_user.password_hash is not None,
            "store_images": current_user.store_images
        }
    }

@router.put("/update-profile", include_in_schema=False)
def update_profile(req: UpdateProfileRequest, db_session: Session = Depends(db.get_db), current_user: db_models.User = Depends(get_current_user)):
    if req.email != current_user.email:
        existing = db_session.query(db_models.User).filter(db_models.User.email == req.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email is already taken")
        current_user.email = req.email.strip()
        
    current_user.name = req.name.strip()
    current_user.store_images = req.store_images
    db_session.commit()
    db_session.refresh(current_user)
    return {
        "status": "success",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name or "",
            "store_images": current_user.store_images
        }
    }

@router.put("/update-password", include_in_schema=False)
def update_password(req: UpdatePasswordRequest, db_session: Session = Depends(db.get_db), current_user: db_models.User = Depends(get_current_user)):
    if current_user.password_hash:
        if not req.current_password or not verify_password(req.current_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="Invalid current password")
            
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
    current_user.password_hash = get_password_hash(req.new_password)
    db_session.commit()
    return {"status": "success"}

@router.post("/register", include_in_schema=False)
def register_user(req: RegisterRequest, db_session: Session = Depends(db.get_db)):
    existing = db_session.query(db_models.User).filter(db_models.User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = get_password_hash(req.password)
    user = db_models.User(email=req.email, name=req.name, password_hash=hashed)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return {"status": "success", "user_id": user.id}

@router.post("/login", include_in_schema=False)
def login_user(req: LoginRequest, db_session: Session = Depends(db.get_db)):
    user = db_session.query(db_models.User).filter(db_models.User.email == req.email).first()
    if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_access_token({"sub": str(user.id)})
    return {"status": "success", "token": token, "user_id": user.id, "email": user.email}

@router.post("/login-face", include_in_schema=False)
async def login_user_face(file: UploadFile = File(...), db_session: Session = Depends(db.get_db)):
    try:
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid or corrupted image")
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(thread_pool, process_global_face_login, img, db_session)
        
        if result.get("status") == "success" and result.get("match"):
            token = create_access_token({"sub": str(result.get("user_id"))})
            return {"status": "success", "token": token, "user_id": result.get("user_id"), "email": result.get("email")}
        else:
            raise HTTPException(status_code=401, detail=result.get("message", "Face not recognized"))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- USER MANAGEMENT CRUD ENDPOINTS ---

@router.get("/users", include_in_schema=False)
def list_users(db_session: Session = Depends(db.get_db), current_user: db_models.User = Depends(get_current_user)):
    users = db_session.query(db_models.User).order_by(db_models.User.created_at.desc()).all()
    return {
        "status": "success",
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name or "",
                "avatar_url": u.avatar_url,
                "has_password": u.password_hash is not None,
                "has_face": len(u.faces) > 0 if u.faces else False,
                "face_count": len(u.faces) if u.faces else 0,
                "api_key_count": len(u.api_keys) if u.api_keys else 0,
                "created_at": u.created_at.isoformat() if u.created_at else None
            }
            for u in users
        ]
    }

@router.post("/users", include_in_schema=False)
def create_user_admin(req: RegisterRequest, db_session: Session = Depends(db.get_db), current_user: db_models.User = Depends(get_current_user)):
    existing = db_session.query(db_models.User).filter(db_models.User.email == req.email.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email is already registered")
    hashed = get_password_hash(req.password)
    user = db_models.User(email=req.email.strip(), name=req.name.strip() if req.name else None, password_hash=hashed)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return {"status": "success", "user": {"id": user.id, "email": user.email, "name": user.name or ""}}

@router.put("/users/{user_id}", include_in_schema=False)
def edit_user(user_id: int, req: EditUserRequest, db_session: Session = Depends(db.get_db), current_user: db_models.User = Depends(get_current_user)):
    user = db_session.query(db_models.User).filter(db_models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if req.email and req.email.strip() != user.email:
        existing = db_session.query(db_models.User).filter(db_models.User.email == req.email.strip()).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email is already used by another user")
        user.email = req.email.strip()
        
    if req.name is not None:
        user.name = req.name.strip()
        
    db_session.commit()
    db_session.refresh(user)
    return {"status": "success", "user": {"id": user.id, "email": user.email, "name": user.name or ""}}

@router.delete("/users/{user_id}", include_in_schema=False)
def delete_user(user_id: int, db_session: Session = Depends(db.get_db), current_user: db_models.User = Depends(get_current_user)):
    user = db_session.query(db_models.User).filter(db_models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Clean up physical face images if any
    import os
    if user.faces:
        for face in user.faces:
            if face.image_url:
                filename = os.path.basename(face.image_url)
                path1 = os.path.join(os.path.dirname(os.path.dirname(__file__)), "controllers", "uploads", "faces", filename)
                path2 = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "faces", filename)
                for p in [path1, path2]:
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass

    db_session.delete(user)
    db_session.commit()
    return {"status": "success", "message": f"User ID {user_id} deleted successfully"}

