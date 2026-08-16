import os
import io
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel, HttpUrl
import requests

from backend.app.core.deps import get_current_user
from backend.app.database import models as db_models
from backend.app.services.anydoc_service import AnyDocService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/anydoc", tags=["AnyDoc Multi-Format Markdown Converter"])


class ConvertUrlRequest(BaseModel):
    url: str
    auto_ocr: bool = True
    force_ocr: bool = False
    format_override: Optional[str] = None


@router.get("/supported-formats", summary="Get Supported Formats & Engines")
def get_supported_formats():
    """
    Returns the complete list of file formats supported by AnyDoc,
    PDF-Inspector, and RapidOCR engines.
    """
    return {
        "status": "success",
        "data": AnyDocService.get_supported_formats()
    }


@router.post("/convert", summary="Convert Document / Image to Markdown")
async def convert_document(
    file: UploadFile = File(..., description="Document file to convert (DOCX, PPTX, XLSX, PDF, CSV, EPUB, Images, etc.)"),
    auto_ocr: bool = Form(True, description="Enable automatic RapidOCR fallback for scanned PDF pages"),
    force_ocr: bool = Form(False, description="Force full RapidOCR extraction across all pages / images"),
    format_override: Optional[str] = Form(None, description="Explicit format override (e.g. 'docx', 'csv', 'xlsx')"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    High-performance multi-format document conversion into GitHub-Flavored Markdown:
    - **Office Docs**: `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.odt`, `.ods`, `.odp`, `.rtf`, `.epub`, `.csv` -> Converted via ultra-fast AnyDoc Rust engine (<10ms).
    - **PDF Documents**: Analyzes structure; if scanned pages are detected and `auto_ocr=True`, passes scanned pages to RapidOCR ONNX layout engine.
    - **Images**: `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp` -> Full OCR layout reconstruction into Markdown headings & tables.
    - **S3 Persistence**: Automatically uploaded and persisted to S3 / Object Storage.
    """
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        result = AnyDocService.convert_document(
            file_bytes=file_bytes,
            filename=file.filename or "document",
            auto_ocr=auto_ocr,
            force_ocr=force_ocr,
            format_override=format_override
        )
        return result

    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[AnyDocController] convert_document error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal document conversion error: {str(e)}")


@router.post("/convert-url", summary="Convert Document from Remote URL")
async def convert_document_from_url(
    req: ConvertUrlRequest,
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Downloads a document from a remote public URL, converts it to Markdown,
    and stores it in S3 object storage.
    """
    try:
        resp = requests.get(req.url, timeout=30)
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to fetch remote document: HTTP {resp.status_code}")

        # Extract filename from URL
        url_path = req.url.split("?")[0]
        filename = os.path.basename(url_path) or "remote_document"

        result = AnyDocService.convert_document(
            file_bytes=resp.content,
            filename=filename,
            auto_ocr=req.auto_ocr,
            force_ocr=req.force_ocr,
            format_override=req.format_override
        )
        return result

    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[AnyDocController] convert-url error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching/converting document from URL: {str(e)}")


@router.post("/batch", summary="Batch Document Conversion")
async def batch_convert_documents(
    files: List[UploadFile] = File(..., description="Multiple document files to convert"),
    auto_ocr: bool = Form(True, description="Enable automatic RapidOCR fallback"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Batch-converts multiple document files simultaneously, returning individual Markdown results
    and overall batch metrics.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided for batch conversion")

    results = []
    total_chars = 0
    total_words = 0
    total_time_ms = 0.0

    for file in files:
        try:
            file_bytes = await file.read()
            if not file_bytes:
                results.append({
                    "filename": file.filename,
                    "status": "error",
                    "error": "File is empty"
                })
                continue

            res = AnyDocService.convert_document(
                file_bytes=file_bytes,
                filename=file.filename or "document",
                auto_ocr=auto_ocr
            )
            results.append(res)
            total_chars += res.get("metrics", {}).get("characters", 0)
            total_words += res.get("metrics", {}).get("words", 0)
            total_time_ms += res.get("metrics", {}).get("processing_time_ms", 0.0)

        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e)
            })

    return {
        "status": "success",
        "total_files": len(files),
        "successful_conversions": sum(1 for r in results if r.get("status") == "success"),
        "total_characters": total_chars,
        "total_words": total_words,
        "total_processing_time_ms": round(total_time_ms, 2),
        "results": results
    }
