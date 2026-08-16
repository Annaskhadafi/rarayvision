from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
import logging

from backend.app.core.deps import get_current_user
from backend.app.database import models as db_models
from backend.app.services.pdf_inspector_service import PdfInspectorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pdf-inspector", tags=["PDF Inspector Microservice"])

def parse_pages_str(pages_str: Optional[str]) -> Optional[List[int]]:
    if not pages_str:
        return None
    try:
        return [int(p.strip()) for p in pages_str.split(",") if p.strip().isdigit()]
    except Exception:
        return None

@router.post("/process", summary="Full PDF Inspection & Hybrid Markdown Extraction")
async def process_pdf(
    file: UploadFile = File(..., description="PDF file to inspect and extract"),
    pages: Optional[str] = Form(None, description="Comma-separated page numbers (e.g. 1,2,5)"),
    auto_ocr: bool = Form(True, description="Enable automatic RapidOCR fallback for scanned pages"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Hybrid PDF engine: Analyzes PDF structure with native parser (<50ms).
    If scanned/image pages are detected and auto_ocr=True, automatically routes those pages
    to RapidOCR and formats bounding boxes into clean Markdown (Headings, Tables, Lists).
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document (.pdf)")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")

        parsed_pages = parse_pages_str(pages)
        result = PdfInspectorService.process_pdf(contents, pages=parsed_pages, auto_ocr=auto_ocr)
        return {
            "status": "success",
            "filename": file.filename,
            "data": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[PdfInspectorController] process_pdf error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal processing error: {str(e)}")

@router.post("/ocr-scanned", summary="Force OCR on Scanned PDF to Markdown")
async def ocr_scanned_pdf(
    file: UploadFile = File(..., description="PDF file to perform full OCR on"),
    pages: Optional[str] = Form(None, description="Comma-separated page numbers (e.g. 1,2)"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Directly applies RapidOCR engine to all (or selected) pages of a scanned PDF,
    reconstructing text positions into structured Markdown with headings and tables.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document (.pdf)")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")

        parsed_pages = parse_pages_str(pages)
        result = PdfInspectorService.ocr_scanned_pdf(contents, pages=parsed_pages)
        return {
            "status": "success",
            "filename": file.filename,
            "data": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[PdfInspectorController] ocr_scanned_pdf error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal OCR error: {str(e)}")

@router.post("/classify", summary="Fast PDF Classification & OCR Detection")
async def classify_pdf(
    file: UploadFile = File(..., description="PDF file to classify"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Ultra-fast PDF classifier (~10-50ms) to check if PDF is text-based or scanned,
    returning confidence score and per-page OCR necessity flags.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document (.pdf)")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")

        result = PdfInspectorService.classify_pdf(contents)
        return {
            "status": "success",
            "filename": file.filename,
            "data": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[PdfInspectorController] classify_pdf error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal classification error: {str(e)}")

@router.post("/extract-text", summary="Extract Plain Text from PDF")
async def extract_text(
    file: UploadFile = File(..., description="PDF file to extract plain text from"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Extracts raw plain text from PDF stream with automatic reading order sorting.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document (.pdf)")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")

        result = PdfInspectorService.extract_text(contents)
        return {
            "status": "success",
            "filename": file.filename,
            "data": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[PdfInspectorController] extract_text error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal text extraction error: {str(e)}")

@router.post("/extract-markdown", summary="Extract Per-Page Markdown")
async def extract_markdown(
    file: UploadFile = File(..., description="PDF file to extract markdown from"),
    pages: Optional[str] = Form(None, description="Comma-separated page numbers"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Extracts structured Markdown page-by-page along with per-page layout metadata.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document (.pdf)")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")

        parsed_pages = parse_pages_str(pages)
        result = PdfInspectorService.extract_markdown(contents, pages=parsed_pages)
        return {
            "status": "success",
            "filename": file.filename,
            "data": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[PdfInspectorController] extract_markdown error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal markdown extraction error: {str(e)}")

@router.post("/extract-positions", summary="Extract Position-Aware Text Tokens")
async def extract_positions(
    file: UploadFile = File(..., description="PDF file to extract positioned text tokens from"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Extracts text tokens along with precise (X, Y) coordinates, width, height, font name, and font size.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document (.pdf)")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")

        result = PdfInspectorService.extract_positions(contents)
        return {
            "status": "success",
            "filename": file.filename,
            "data": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[PdfInspectorController] extract_positions error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal position extraction error: {str(e)}")

@router.post("/extract-structure", summary="Extract Tagged PDF Structure Elements")
async def extract_structure(
    file: UploadFile = File(..., description="PDF file to extract structure tree elements from"),
    current_user: db_models.User = Depends(get_current_user)
):
    """
    Extracts structure elements (H1, Paragraph, Table, etc.) from tagged PDFs.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document (.pdf)")

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")

        result = PdfInspectorService.extract_structure(contents)
        return {
            "status": "success",
            "filename": file.filename,
            "data": result
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"[PdfInspectorController] extract_structure error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal structure extraction error: {str(e)}")
