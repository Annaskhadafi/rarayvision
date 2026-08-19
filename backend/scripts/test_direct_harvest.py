import os
import sys
import time
import cv2
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.database.database import SessionLocal
from backend.app.database import models as db_models
from backend.app.services.ml_service import auto_harvest_face_on_match

sample_img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "assets", "img2.jpeg"))
img = cv2.imread(sample_img_path)

db_session = SessionLocal()
try:
    first_face = db_session.query(db_models.Face).first()
    if first_face:
        print(f"[*] Testing Auto-Harvest on Face ID: '{first_face.face_id}' ({first_face.name})")
        print(f"[*] Before -> Image URL: {first_face.image_url}, Embedding V2: {bool(first_face.embedding_v2)}")

        # Trigger auto-harvest
        auto_harvest_face_on_match(img, first_face.user_id, first_face.face_id, "https://vision.chitraparatama.com")
        
        # Wait 3s for background thread
        time.sleep(3)
        
        db_session.refresh(first_face)
        print(f"[+] After  -> Image URL: {first_face.image_url}, Embedding V2: {bool(first_face.embedding_v2)}")
        if first_face.embedding_v2:
            import json
            v2_vec = json.loads(first_face.embedding_v2)
            print(f"[+] Embedding V2 Length: {len(v2_vec)} floats")
            print("[OK] Auto-Harvesting & Background Migration verified successfully!")
finally:
    db_session.close()
