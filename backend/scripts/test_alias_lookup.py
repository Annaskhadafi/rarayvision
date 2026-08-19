import os
import sys
import cv2
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.database.database import SessionLocal
from backend.app.database import models as db_models
from backend.app.services.ml_service import process_register_logic

sample_img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "assets", "img2.jpeg"))
img = cv2.imread(sample_img_path)

db_session = SessionLocal()
try:
    user = db_session.query(db_models.User).first()
    
    # Test Annas Khadafi SN 71261
    emp_str = "71261"
    candidate_ids = [
        emp_str,
        f"emp-{emp_str}",
        emp_str.replace("emp-", "")
    ]
    
    stored_face = db_session.query(db_models.Face).filter(
        db_models.Face.user_id == user.id,
        db_models.Face.face_id.in_(candidate_ids)
    ).first()

    print(f"[*] Testing candidate IDs: {candidate_ids}")
    if stored_face:
        print(f"[+] Found stored face: face_id='{stored_face.face_id}', name='{stored_face.name}'")
        import json
        stored_emb = np.array(json.loads(stored_face.embedding), dtype=np.float32)
        
        # Live extraction
        reg = process_register_logic(img, check_spoof=False)
        if reg.get("status") == "success":
            live_emb = np.array(reg["embedding"], dtype=np.float32)
            dot = float(np.dot(live_emb, stored_emb))
            norm_live = float(np.linalg.norm(live_emb))
            norm_stored = float(np.linalg.norm(stored_emb))
            sim = dot / (norm_live * norm_stored)
            print(f"[+] Cosine Similarity: {sim:.4f}")
            print(f"[+] Verified (threshold 0.45): {sim >= 0.45}")
    else:
        print("[-] Face record not found!")
finally:
    db_session.close()
