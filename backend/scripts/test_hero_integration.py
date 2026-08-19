import os
import sys
import cv2
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.database.database import SessionLocal
from backend.app.database import models as db_models
from backend.app.services.ml_service import (
    get_tenant_faces,
    process_recognize_live,
    auto_harvest_face_on_match
)

sample_img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "assets", "img2.jpeg"))
img = cv2.imread(sample_img_path)

db_session = SessionLocal()
try:
    user = db_session.query(db_models.User).first()
    print(f"[*] Testing with User #{user.id} ({user.email})")

    tenant_faces = get_tenant_faces(db_session, user.id)
    print(f"[*] Tenant faces loaded: {len(tenant_faces)}")

    # 1. Run recognition (simulate HERO attendance scan)
    result = process_recognize_live(img, tenant_faces, mode="identify")
    print(f"[*] HERO Attendance Recognition Result: {result.get('status')}, Match: {result.get('match')}")

    if result.get("match") and result.get("data", {}).get("id"):
        matched_id = result["data"]["id"]
        print(f"[*] Matched Employee/Face ID: {matched_id}")
        print("[*] Triggering Auto-Harvest (Saving photo + Extracting V2 Embedding in background)...")
        auto_harvest_face_on_match(img, user.id, matched_id, "https://vision.chitraparatama.com")
        
        # Wait a moment for background thread to commit
        import time
        time.sleep(2)
        
        # Check DB
        face_record = db_session.query(db_models.Face).filter(
            db_models.Face.user_id == user.id,
            db_models.Face.face_id == str(matched_id)
        ).first()
        
        if face_record:
            has_photo = bool(face_record.image_url)
            has_v2 = bool(face_record.embedding_v2)
            print(f"[+] Verification: Face '{face_record.name}' -> Has Photo URL: {has_photo} ({face_record.image_url}), Has V2 Embedding: {has_v2}")

finally:
    db_session.close()
