import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.database.database import SessionLocal
from backend.app.database import models as db_models

db_session = SessionLocal()
try:
    faces = db_session.query(db_models.Face).filter(db_models.Face.name.ilike('%Annas%')).all()
    print(f"Total Annas faces in DB: {len(faces)}")
    for f in faces:
        print(f"- ID: {f.face_id} | Name: {f.name} | Image: {f.image_url} | Has V2: {bool(f.embedding_v2)}")
finally:
    db_session.close()
