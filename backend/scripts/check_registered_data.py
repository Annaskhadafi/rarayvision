import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.database.database import SessionLocal, engine
from backend.app.database import models as db_models

db = SessionLocal()
try:
    users = db.query(db_models.User).all()
    faces = db.query(db_models.Face).all()
    
    print("==================================================")
    print("       LAPORAN STATUS DATA REGISTER WAJAH        ")
    print("==================================================")
    print(f"Total Users di DB : {len(users)}")
    print(f"Total Faces di DB : {len(faces)}")
    
    # Cek setting store_images pada tiap user
    users_with_store = [u for u in users if getattr(u, 'store_images', False)]
    print(f"User dengan 'store_images = True' : {len(users_with_store)} / {len(users)}")
    for u in users:
        print(f"  - User #{u.id} ({u.email}): Name='{u.name}', store_images={getattr(u, 'store_images', False)}")

    # Cek kolom image_url pada tabel Face
    faces_with_url = [f for f in faces if f.image_url]
    faces_without_url = [f for f in faces if not f.image_url]
    print(f"\nFaces dengan kolom image_url terisi : {len(faces_with_url)} / {len(faces)}")
    print(f"Faces tanpa image_url (vector only) : {len(faces_without_url)} / {len(faces)}")

    # Cek folder fisik foto
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    uploads_dirs = [
        os.path.join(base_dir, "uploads", "faces"),
        os.path.join(base_dir, "controllers", "uploads", "faces"),
        os.path.join(os.path.dirname(base_dir), "uploads", "faces"),
    ]

    print("\n--- STATUS FILE FISIK DI DISK ---")
    total_physical_files = 0
    for udir in uploads_dirs:
        if os.path.exists(udir):
            files = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f))]
            print(f"Folder: {udir}")
            print(f"  -> Ditemukan {len(files)} file foto.")
            total_physical_files += len(files)
            if files:
                print(f"  -> Contoh file: {files[:5]}")
        else:
            print(f"Folder: {udir} (Belum ada / belum dibuat)")

    # Verifikasi apakah file di image_url benar-benar ada di disk
    print("\n--- VERIFIKASI KEBERADAAN FILE FOTO MASING-MASING FACE ---")
    valid_file_count = 0
    missing_file_count = 0
    
    for f in faces:
        if f.image_url:
            filename = os.path.basename(f.image_url)
            found = False
            for udir in uploads_dirs:
                if os.path.exists(os.path.join(udir, filename)):
                    found = True
                    break
            if found:
                valid_file_count += 1
            else:
                missing_file_count += 1
        
    print(f"Face yang file fotonya LENGKAP & VALID di disk : {valid_file_count} / {len(faces)}")
    if missing_file_count > 0:
        print(f"Face yang URL-nya ada tapi file fisiknya hilang : {missing_file_count}")

    print("\n--- SAMPLE 5 DATA FACE TERBARU ---")
    for f in faces[-5:]:
        emb_valid = f.embedding is not None and len(f.embedding) > 50
        print(f"• ID: {f.face_id} | Name: {f.name} | User_ID: {f.user_id} | Image: {f.image_url or 'None'} | Vector Embedding: {'OK' if emb_valid else 'EMPTY'}")

    print("==================================================")
finally:
    db.close()
