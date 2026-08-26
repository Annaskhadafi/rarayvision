import os
import io
import time
import uuid
import logging
import mimetypes
from typing import Optional, Dict, Any, List
import numpy as np

import anydoc
try:
    from app.services.s3_service import upload_file_to_s3
    from app.services.pdf_inspector_service import (
        PdfInspectorService,
        get_rapid_ocr,
        format_ocr_to_markdown
    )
except ImportError:
    from backend.app.services.s3_service import upload_file_to_s3
    from backend.app.services.pdf_inspector_service import (
        PdfInspectorService,
        get_rapid_ocr,
        format_ocr_to_markdown
    )

logger = logging.getLogger(__name__)

# Supported extensions grouped by engine
ANYDOC_EXTENSIONS = {
    "docx", "doc", "pptx", "ppt", "xlsx", "xls",
    "odt", "ods", "odp", "rtf", "epub", "csv", "tsv"
}

PDF_EXTENSIONS = {"pdf"}

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif"}

TEXT_EXTENSIONS = {"txt", "md", "markdown", "json", "xml", "html", "htm", "log", "yaml", "yml"}

CONTENT_TYPE_MAP = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "epub": "application/epub+zip",
    "rtf": "application/rtf",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "txt": "text/plain",
    "md": "text/markdown",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


class AnyDocService:
    @staticmethod
    def get_supported_formats() -> Dict[str, Any]:
        """Returns catalog of all supported document formats and conversion engines."""
        return {
            "anydoc_office": list(sorted(ANYDOC_EXTENSIONS)),
            "pdf": list(sorted(PDF_EXTENSIONS)),
            "images_ocr": list(sorted(IMAGE_EXTENSIONS)),
            "plain_text": list(sorted(TEXT_EXTENSIONS)),
            "all_supported": list(sorted(ANYDOC_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS | TEXT_EXTENSIONS)),
            "engines": [
                {
                    "name": "anydoc",
                    "description": "Blazing-fast Rust engine for Word, Excel, PowerPoint, OpenDoc, RTF, EPUB, CSV, and digital PDFs (<10ms).",
                    "formats": list(sorted(ANYDOC_EXTENSIONS))
                },
                {
                    "name": "pdf_inspector_hybrid",
                    "description": "Hybrid PDF structural inspector with automated RapidOCR fallback for scanned pages.",
                    "formats": ["pdf"]
                },
                {
                    "name": "rapidocr_vision",
                    "description": "RapidOCR ONNX engine for direct image text & tabular spatial reconstruction into Markdown.",
                    "formats": list(sorted(IMAGE_EXTENSIONS))
                }
            ]
        }

    @staticmethod
    def _save_file_locally_and_s3(file_bytes: bytes, original_filename: str, ext: str) -> Dict[str, Optional[str]]:
        """
        Saves uploaded file to local /uploads directory and uploads to S3 object storage if configured.
        """
        unique_id = uuid.uuid4().hex[:10]
        safe_name = os.path.splitext(original_filename)[0].replace(" ", "_")
        stored_filename = f"{unique_id}_{safe_name}.{ext}" if ext else f"{unique_id}_{safe_name}"
        
        # 1. Local storage save
        uploads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        local_path = os.path.join(uploads_dir, stored_filename)
        
        try:
            with open(local_path, "wb") as f:
                f.write(file_bytes)
            local_url = f"/api/v1/uploads/{stored_filename}"
        except Exception as e:
            logger.error(f"[AnyDocService] Failed to save file locally: {e}")
            local_url = None

        # 2. S3 Object Storage upload
        content_type = CONTENT_TYPE_MAP.get(ext.lower(), "application/octet-stream")
        s3_url = None
        try:
            s3_url = upload_file_to_s3(file_bytes, stored_filename, content_type=content_type)
        except Exception as e:
            logger.warning(f"[AnyDocService] S3 upload error: {e}")

        return {
            "stored_filename": stored_filename,
            "local_url": local_url,
            "s3_url": s3_url or local_url, # Fallback to local URL if S3 not set up
            "is_s3": bool(s3_url)
        }

    @classmethod
    def convert_document(
        cls,
        file_bytes: bytes,
        filename: str,
        auto_ocr: bool = True,
        force_ocr: bool = False,
        format_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Converts any document or image into clean GitHub-Flavored Markdown.
        Automatically stores file in S3 / local storage.
        """
        start_time = time.perf_counter()
        
        # Determine extension
        ext = ""
        if format_override:
            ext = format_override.lower().strip(".")
        elif "." in filename:
            ext = filename.rsplit(".", 1)[-1].lower().strip()

        # Save to S3 / local
        storage_info = cls._save_file_locally_and_s3(file_bytes, filename, ext)

        markdown_output = ""
        engine_used = "anydoc"
        ocr_applied = False
        extra_meta = {}

        try:
            # 1. Image formats -> RapidOCR layout reconstruction
            if ext in IMAGE_EXTENSIONS:
                engine_used = "rapidocr_vision"
                ocr_applied = True
                markdown_output = cls._convert_image(file_bytes)

            # 2. PDF Documents -> AnyDoc Native + Hybrid Fallback
            elif ext in PDF_EXTENSIONS:
                if force_ocr:
                    engine_used = "rapidocr_pdf_forced"
                    ocr_applied = True
                    ocr_res = PdfInspectorService.ocr_scanned_pdf(file_bytes)
                    markdown_output = ocr_res.get("markdown", "")
                    extra_meta["page_count"] = ocr_res.get("page_count", 0)
                else:
                    # 1. Try fast native AnyDoc extraction first (high speed, <1s, 0 memory footprint)
                    try:
                        markdown_output = anydoc.to_markdown_bytes(file_bytes, format="pdf")
                        engine_used = "anydoc_native_pdf"
                    except Exception as anydoc_err:
                        logger.info(f"[AnyDocService] anydoc native PDF parse fallback: {anydoc_err}")
                        markdown_output = ""

                    # 2. If AnyDoc extracted rich text, use it immediately
                    if markdown_output and len(markdown_output.strip()) > 200:
                        ocr_applied = False
                        extra_meta["pdf_type"] = "digital_text"
                    else:
                        # 3. Hybrid fallback: analyzes structure with safe OCR limits
                        engine_used = "pdf_inspector_hybrid"
                        pdf_res = PdfInspectorService.process_pdf(file_bytes, auto_ocr=auto_ocr)
                        hybrid_md = pdf_res.get("markdown", "")
                        if hybrid_md and len(hybrid_md.strip()) > 0:
                            markdown_output = hybrid_md
                        ocr_applied = len(pdf_res.get("ocr_applied_pages", [])) > 0
                        extra_meta["pdf_type"] = pdf_res.get("pdf_type")
                        extra_meta["page_count"] = pdf_res.get("page_count")
                        extra_meta["ocr_applied_pages"] = pdf_res.get("ocr_applied_pages", [])
                        extra_meta["confidence"] = pdf_res.get("confidence")

            # 3. Office & Structured Documents -> AnyDoc Rust Engine
            elif ext in ANYDOC_EXTENSIONS:
                engine_used = "anydoc"
                try:
                    # Pass format explicitly to avoid signature ambiguity in CSV/TSV/etc.
                    markdown_output = anydoc.to_markdown_bytes(file_bytes, format=ext)
                except Exception as anydoc_err:
                    logger.warning(f"[AnyDocService] anydoc.to_markdown_bytes with format={ext} failed: {anydoc_err}, trying auto-detect")
                    markdown_output = anydoc.to_markdown_bytes(file_bytes)

            # 4. Plain Text Formats
            elif ext in TEXT_EXTENSIONS:
                engine_used = "plain_text"
                try:
                    text_content = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    text_content = file_bytes.decode("latin-1", errors="replace")
                
                if ext in {"md", "markdown"}:
                    markdown_output = text_content
                elif ext == "json":
                    markdown_output = f"```json\n{text_content}\n```"
                elif ext in {"xml", "html", "htm"}:
                    markdown_output = f"```html\n{text_content}\n```"
                else:
                    markdown_output = text_content

            # 5. Unknown format fallback -> try anydoc auto detection
            else:
                engine_used = "anydoc_autodetect"
                try:
                    markdown_output = anydoc.to_markdown_bytes(file_bytes)
                except Exception as unknown_err:
                    logger.warning(f"[AnyDocService] anydoc auto-detect failed for {filename}: {unknown_err}")
                    # Try plain text fallback
                    try:
                        markdown_output = file_bytes.decode("utf-8")
                    except Exception:
                        raise ValueError(f"Unsupported or unrecognized document format: '.{ext}'. Please provide a supported document type.")

        except Exception as convert_err:
            logger.error(f"[AnyDocService] Error during document conversion: {convert_err}", exc_info=True)
            raise ValueError(f"Failed to convert '{filename}': {str(convert_err)}")

        # Extract and insert embedded images for PDF documents
        if ext == "pdf" and markdown_output:
            try:
                markdown_output = cls.insert_images_into_markdown(file_bytes, markdown_output)
            except Exception as extract_err:
                logger.error(f"[AnyDocService] Image extraction failed: {extract_err}", exc_info=True)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        char_count = len(markdown_output)
        word_count = len(markdown_output.split()) if markdown_output else 0
        line_count = len(markdown_output.splitlines()) if markdown_output else 0

        return {
            "status": "success",
            "filename": filename,
            "format": ext or "unknown",
            "engine": engine_used,
            "ocr_applied": ocr_applied,
            "markdown": markdown_output,
            "metrics": {
                "file_size_bytes": len(file_bytes),
                "characters": char_count,
                "words": word_count,
                "lines": line_count,
                "processing_time_ms": elapsed_ms
            },
            "storage": {
                "s3_url": storage_info["s3_url"],
                "local_url": storage_info["local_url"],
                "stored_filename": storage_info["stored_filename"],
                "is_s3": storage_info["is_s3"]
            },
            "meta": extra_meta
        }

    @staticmethod
    def _convert_image(file_bytes: bytes) -> str:
        """Runs RapidOCR on image bytes and converts spatial detections to Markdown."""
        ocr_engine = get_rapid_ocr()
        if not ocr_engine:
            raise ValueError("RapidOCR ONNX engine is not available on this server.")

        try:
            import cv2
            nparr = np.frombuffer(file_bytes, np.uint8)
            img_np = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img_np is None:
                raise ValueError("cv2 decode returned None")
        except Exception:
            from PIL import Image
            image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            img_np = np.array(image)

        ocr_result, _ = ocr_engine(img_np)
        return format_ocr_to_markdown(ocr_result)

    @classmethod
    def insert_images_into_markdown(cls, file_bytes: bytes, markdown_text: str) -> str:
        """
        Scans PDF pages using pypdfium2, extracts embedded images (resolution >= 150x150),
        saves them locally, and inserts Markdown image links at the corresponding page locations.
        """
        import pypdfium2 as pdfium
        from pypdfium2.raw import FPDF_PAGEOBJ_IMAGE
        import uuid
        import re
        from PIL import Image

        try:
            pdf_doc = pdfium.PdfDocument(file_bytes)
        except Exception as e:
            logger.warning(f"[AnyDocService] Could not open PDF with pypdfium2 for image extraction: {e}")
            return markdown_text

        total_pages = len(pdf_doc)
        page_images = {}
        has_extracted_any = False

        # Get uploads directory
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        uploads_dir = os.path.join(backend_dir, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)

        for page_idx in range(total_pages):
            page_num = page_idx + 1
            page = pdf_doc[page_idx]
            img_list = []
            img_count = 0

            try:
                # Retrieve FPDF image objects
                for obj in page.get_objects(filter=[FPDF_PAGEOBJ_IMAGE]):
                    if isinstance(obj, pdfium.PdfImage):
                        try:
                            bitmap = obj.get_bitmap()
                            width = bitmap.width
                            height = bitmap.height

                            # Minimum resolution check (150x150 px)
                            if width >= 150 and height >= 150:
                                pil_image = bitmap.to_pil()
                                unique_img_id = uuid.uuid4().hex[:10]
                                img_filename = f"extracted_{unique_img_id}_p{page_num}_{img_count}.png"
                                img_path = os.path.join(uploads_dir, img_filename)
                                pil_image.save(img_path, format="PNG")

                                # Upload to S3 if configured
                                s3_url = None
                                try:
                                    with open(img_path, "rb") as img_f:
                                        img_bytes = img_f.read()
                                    from app.services.s3_service import upload_file_to_s3
                                    s3_url = upload_file_to_s3(img_bytes, img_filename, content_type="image/png")
                                except Exception:
                                    try:
                                        from backend.app.services.s3_service import upload_file_to_s3
                                        s3_url = upload_file_to_s3(img_bytes, img_filename, content_type="image/png")
                                    except Exception:
                                        pass

                                img_url = s3_url or f"/api/v1/uploads/{img_filename}"
                                img_list.append(f"![Diagram Halaman {page_num} - Gambar {img_count+1}]({img_url})")
                                img_count += 1
                                has_extracted_any = True
                        except Exception as img_err:
                            logger.debug(f"[AnyDocService] Object image extraction failed: {img_err}")
            except Exception as page_err:
                logger.warning(f"[AnyDocService] Error scanning page {page_num} images: {page_err}")

            if img_list:
                page_images[page_num] = img_list

        pdf_doc.close()

        if not has_extracted_any:
            return markdown_text

        modified_markdown = markdown_text

        # Insert page image links near page indicators or headers
        for page_num, img_tags in page_images.items():
            tags_str = "\n\n" + "\n".join(img_tags) + "\n\n"

            # Look for standard comments: <!-- Page X ... -->
            pattern = rf"(<!--\s*Page\s*{page_num}(?:\s+\([^)]+\))?\s*-->)"
            match = re.search(pattern, modified_markdown, re.IGNORECASE)

            if match:
                marker = match.group(1)
                modified_markdown = re.sub(
                    re.escape(marker),
                    f"{marker}{tags_str}",
                    modified_markdown,
                    count=1,
                    flags=re.IGNORECASE
                )
            else:
                # Look for header markers: "Page X" or "Halaman X"
                text_pattern = rf"(^|\n)(Page\s*{page_num}\b|Halaman\s*{page_num}\b)"
                text_match = re.search(text_pattern, modified_markdown, re.IGNORECASE)
                if text_match:
                    matched_text = text_match.group(2)
                    modified_markdown = re.sub(
                        re.escape(matched_text),
                        f"{matched_text}{tags_str}",
                        modified_markdown,
                        count=1,
                        flags=re.IGNORECASE
                    )
                else:
                    # Fallback: append to the end
                    page_header = f"\n\n### Diagram Referensi Halaman {page_num}\n"
                    modified_markdown += page_header + "\n".join(img_tags)

        return modified_markdown
