import os
import sys
import uuid
import time
import logging

from dotenv import load_dotenv

# Ensure backend package can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from backend.app.database.database import SessionLocal
from backend.app.database.rag_models import RagDocument, RagDocumentChunk
from backend.app.services.rag_service import RagService
from backend.app.services.anydoc_service import AnyDocService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def rechunk_all():
    db = SessionLocal()
    try:
        documents = db.query(RagDocument).all()
        logger.info(f"=== Memulai Re-Chunking untuk {len(documents)} dokumen di Knowledge Base ===")

        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        uploads_dir = os.path.join(backend_dir, "uploads")
        logger.info(f"Direktori Uploads: {uploads_dir}")

        success_count = 0
        skipped_count = 0
        failed_count = 0

        for idx, doc in enumerate(documents, 1):
            logger.info(f"\n--- [{idx}/{len(documents)}] Memproses: '{doc.filename}' (ID: {doc.id}) ---")
            
            # 1. Cari file fisik dokumen
            candidate_files = []
            
            # S3 stored filename dari metadata
            if doc.extra_meta and isinstance(doc.extra_meta, dict):
                stored_name = doc.extra_meta.get("s3_stored_filename")
                if stored_name:
                    candidate_files.append(os.path.join(uploads_dir, stored_name))

            # Dari local_url
            if doc.local_url:
                clean_local = os.path.basename(doc.local_url)
                candidate_files.append(os.path.join(uploads_dir, clean_local))

            # Dari s3_url
            if doc.s3_url:
                clean_s3 = os.path.basename(doc.s3_url)
                candidate_files.append(os.path.join(uploads_dir, clean_s3))

            # Langsung dengan filename asli di uploads
            candidate_files.append(os.path.join(uploads_dir, doc.filename))

            target_file_path = None
            for p in candidate_files:
                if os.path.exists(p) and os.path.isfile(p):
                    target_file_path = p
                    break

            if not target_file_path:
                # Cari file yang mirip di uploads_dir
                safe_stem = os.path.splitext(doc.filename)[0].replace(" ", "_")
                for f in os.listdir(uploads_dir) if os.path.exists(uploads_dir) else []:
                    if safe_stem in f or (doc.id[:8] in f):
                        target_file_path = os.path.join(uploads_dir, f)
                        break

            # Jika file fisik belum ada di uploads, coba unduh dari S3
            if not target_file_path:
                logger.info(f"File belum ada di lokal, mencoba unduh dari S3 Storage...")
                s3_keys_to_try = []
                if doc.extra_meta and isinstance(doc.extra_meta, dict):
                    stored_name = doc.extra_meta.get("s3_stored_filename")
                    if stored_name:
                        s3_keys_to_try.append(stored_name)

                if doc.s3_url:
                    from urllib.parse import urlparse
                    parsed = urlparse(doc.s3_url)
                    clean_path = parsed.path.lstrip("/")
                    # Cloudhost prefix format: /onechitra/upload/... or /upload/...
                    if clean_path.startswith("onechitra/upload/"):
                        s3_keys_to_try.append(clean_path.replace("onechitra/upload/", ""))
                    elif clean_path.startswith("onechitra/"):
                        s3_keys_to_try.append(clean_path.replace("onechitra/", ""))
                    elif clean_path.startswith("upload/"):
                        s3_keys_to_try.append(clean_path.replace("upload/", ""))
                    else:
                        s3_keys_to_try.append(os.path.basename(doc.s3_url))

                from backend.app.services.s3_service import get_presigned_download_url
                import requests

                downloaded_file_path = None
                for key_cand in s3_keys_to_try:
                    if not key_cand:
                        continue
                    try:
                        dl_url = get_presigned_download_url(key_cand, expires_in=600)
                        if dl_url:
                            resp = requests.get(dl_url, stream=True, timeout=20)
                            if resp.status_code == 200:
                                os.makedirs(uploads_dir, exist_ok=True)
                                save_dest = os.path.join(uploads_dir, os.path.basename(key_cand))
                                with open(save_dest, "wb") as f_out:
                                    for chunk in resp.iter_content(chunk_size=65536):
                                        f_out.write(chunk)
                                downloaded_file_path = save_dest
                                logger.info(f"⬇️ Berhasil mengunduh '{key_cand}' dari S3 -> {save_dest}")
                                break
                    except Exception as ex:
                        logger.warning(f"Gagal unduh S3 key '{key_cand}': {ex}")

                if downloaded_file_path and os.path.exists(downloaded_file_path):
                    target_file_path = downloaded_file_path

            if not target_file_path:
                logger.error(f"❌ File fisik '{doc.filename}' benar-benar tidak ditemukan baik di lokal maupun di S3. Melewati dokumen ini.")
                skipped_count += 1
                continue

            logger.info(f"Ditemukan file fisik: {target_file_path} (Ukuran: {os.path.getsize(target_file_path)} bytes)")

            # 2. Baca bytes
            with open(target_file_path, "rb") as f:
                file_bytes = f.read()

            if not file_bytes:
                logger.warning(f"File kosong untuk '{doc.filename}'. Melewati.")
                skipped_count += 1
                continue

            # 3. Jalankan AnyDoc conversion dengan image extraction
            ext = os.path.splitext(doc.filename)[1].lower().strip(".") or doc.format.lower().strip(".")
            logger.info(f"Menjalankan AnyDoc conversion & ekstraksi gambar (Format: {ext})...")

            try:
                conv_res = AnyDocService.convert_document(
                    file_bytes=file_bytes,
                    filename=doc.filename,
                    auto_ocr=True,
                    force_ocr=False,
                    format_override=ext
                )
                markdown_text = conv_res.get("markdown", "")
                logger.info(f"AnyDoc selesai: {len(markdown_text)} karakter Markdown dihasilkan.")

                # Hitung jumlah tag gambar yang ditemukan di Markdown hasil ekstraksi
                import re
                images_found = re.findall(r'!\[(.*?)\]\((.*?)\)', markdown_text)
                logger.info(f"🖼️ Total gambar diekstrak / disisipkan: {len(images_found)} gambar")
                for img_alt, img_url in images_found[:5]:
                    logger.info(f"   -> [{img_alt}]: {img_url}")
                if len(images_found) > 5:
                    logger.info(f"   -> ... dan {len(images_found) - 5} gambar lainnya.")

                # 4. Semantic chunking
                chunk_dicts = RagService.split_markdown_into_chunks(markdown_text)
                if not chunk_dicts:
                    chunk_dicts = [{
                        "content": markdown_text or "Empty document",
                        "heading": "Document Content",
                        "char_count": len(markdown_text),
                        "token_estimate": len(markdown_text.split()) if markdown_text else 0
                    }]

                logger.info(f"Dokumen dipecah menjadi {len(chunk_dicts)} potongan chunks semantik.")

                # 5. Generate embeddings
                chunk_texts = [c["content"] for c in chunk_dicts]
                logger.info("Menghitung vector embeddings...")
                embeddings = RagService.generate_embeddings(chunk_texts)

                # 6. Hapus chunks lama untuk dokumen ini
                old_chunks_count = db.query(RagDocumentChunk).filter(RagDocumentChunk.document_id == doc.id).count()
                db.query(RagDocumentChunk).filter(RagDocumentChunk.document_id == doc.id).delete(synchronize_session=False)
                logger.info(f"Menghapus {old_chunks_count} chunk lama.")

                # 7. Masukkan chunks baru
                for c_idx, (c_dict, emb) in enumerate(zip(chunk_dicts, embeddings)):
                    chunk_rec = RagDocumentChunk(
                        id=str(uuid.uuid4()),
                        document_id=doc.id,
                        chunk_index=c_idx,
                        content=c_dict["content"],
                        heading=c_dict.get("heading"),
                        token_count=c_dict.get("token_estimate", 0),
                        embedding=emb,
                        metadata_info={
                            "char_count": c_dict.get("char_count", len(c_dict["content"])),
                            "chunk_index": c_idx,
                            "heading": c_dict.get("heading")
                        }
                    )
                    db.add(chunk_rec)

                # 8. Update metadata dokumen
                doc.char_count = len(markdown_text)
                doc.word_count = len(markdown_text.split()) if markdown_text else 0
                doc.total_chunks = len(chunk_dicts)
                doc.engine_used = conv_res.get("engine", doc.engine_used)
                if not doc.extra_meta or not isinstance(doc.extra_meta, dict):
                    doc.extra_meta = {}
                doc.extra_meta["images_extracted_count"] = len(images_found)
                doc.extra_meta["last_rechunked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

                db.commit()
                logger.info(f"✅ Berhasil re-chunk '{doc.filename}' ({len(chunk_dicts)} chunks baru, {len(images_found)} gambar terlampir).")
                success_count += 1

            except Exception as e:
                db.rollback()
                logger.error(f"❌ Gagal memproses '{doc.filename}': {e}", exc_info=True)
                failed_count += 1

        # 9. Invalidate chunk cache agar query berikutnya mengambil chunk & vector terbaru
        RagService._invalidate_chunk_cache()
        logger.info("\n=== Rangkuman Re-Chunking ===")
        logger.info(f"Total Dokumen : {len(documents)}")
        logger.info(f"Sukses        : {success_count}")
        logger.info(f"Dilewati      : {skipped_count}")
        logger.info(f"Gagal         : {failed_count}")
        logger.info("Memory vector & disk cache telah di-invalidasi.")

    except Exception as e:
        logger.error(f"Fatal error saat rechunking: {e}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    rechunk_all()
