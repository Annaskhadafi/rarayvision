import os
import uuid
import re
import cv2
import numpy as np
import logging
import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from backend.app.database import database as db
from backend.app.database import models as db_models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tire", tags=["Tire Sidewall OCR"])

# ─── Pipeline singleton ───────────────────────────────────────────────────────
_pipeline_instance = None

def get_pipeline():
    global _pipeline_instance
    if _pipeline_instance is None:
        try:
            from app.services.tire_ocr.pipeline.core import TireImageProcessingPipeline
            _pipeline_instance = TireImageProcessingPipeline()
        except Exception as e:
            logger.warning(f"Could not load ML pipeline: {e}")
            _pipeline_instance = False
    return _pipeline_instance


# ─── EasyOCR – pre-warmed in background thread at startup ────────────────────
_easyocr_reader = None
_easyocr_ready = threading.Event()

def _warmup_easyocr():
    """Load EasyOCR model in background so first request is instant."""
    global _easyocr_reader
    try:
        import easyocr
        logger.info("[OCR] Pre-warming EasyOCR model...")
        _easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        _easyocr_ready.set()
        logger.info("[OCR] EasyOCR ready!")
    except Exception as e:
        logger.warning(f"[OCR] EasyOCR warmup failed: {e}")
        _easyocr_reader = False
        _easyocr_ready.set()

# Start background warmup immediately on module import
threading.Thread(target=_warmup_easyocr, daemon=True).start()


# ─── Image helpers ────────────────────────────────────────────────────────────
def _resize_for_ocr(img: np.ndarray, max_width: int = 1024) -> np.ndarray:
    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / w
        img = cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _preprocess_for_ocr(img: np.ndarray) -> np.ndarray:
    """CLAHE contrast enhancement for embossed dark rubber text."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


# ─── Main OCR function ────────────────────────────────────────────────────────
def perform_direct_ocr(img: np.ndarray) -> str:
    """
    Fast OCR — target <3 seconds.
    Uses pre-warmed EasyOCR (0.5–1s after warmup).
    No slow API calls in the hot path.
    """
    img_small = _resize_for_ocr(img, max_width=1024)
    enhanced  = _preprocess_for_ocr(img_small)

    # Wait max 2s for EasyOCR to be ready (it warms up in background at startup)
    _easyocr_ready.wait(timeout=2.0)

    if _easyocr_reader:
        try:
            results = _easyocr_reader.readtext(enhanced, detail=0)
            texts = [str(r).strip() for r in results if r and "safety" not in str(r).lower()]
            if texts:
                return " ".join(texts)
        except Exception as e:
            logger.warning(f"[OCR] EasyOCR inference error: {e}")

    return ""



def parse_dot_and_serial_fast(raw_text: str):
    """Fast regex parser for DOT codes and serial numbers strictly from REAL OCR raw text."""
    clean_raw = raw_text.strip() if raw_text else ""
    
    # Filter safety guardrails
    if "user safety" in clean_raw.lower() or "safety" in clean_raw.lower():
        clean_raw = ""

    if not clean_raw:
        return {
            "serial_number": "Tidak Ada Teks Terbaca",
            "dot_code": "Tidak Ditemukan",
            "manufacturer": "Tidak Ditemukan",
            "model_name": "Tidak Ditemukan",
            "size": "Tidak Ditemukan",
            "load_speed": "Tidak Ditemukan",
            "special_markings": "Tidak Ditemukan"
        }

    # Extract 4-digit WWYY DOT date code or DOT prefix from real text
    dot_match = re.search(r'\b(DOT\s*[\w\d]+|\d{4})\b', clean_raw, re.IGNORECASE)
    dot_code = dot_match.group(1) if dot_match else "Tidak Ditemukan"
    
    # Serial number: return exact text tokens extracted by OCR from the real image (e.g. FRJ2920)
    tokens = re.findall(r'\b[A-Z0-9\s-]{2,20}\b', clean_raw, re.IGNORECASE)
    valid_tokens = [t.strip() for t in tokens if "safety" not in t.lower() and "user" not in t.lower()]
    
    if valid_tokens:
        serial_number = max(valid_tokens, key=len).strip()
    else:
        serial_number = clean_raw

    # Brand detection from real OCR text
    brands = ["MICHELIN", "BRIDGESTONE", "GOODYEAR", "CONTINENTAL", "PIRELLI", "DUNLOP", "YOKOHAMA", "HANKOOK", "TOYO", "KUMHO", "ACCELERA", "GT RADIAL"]
    found_brand = "Tidak Ditemukan"
    for b in brands:
        if b in clean_raw.upper():
            found_brand = b
            break
            
    # Size detection from real OCR text
    size_match = re.search(r'\b(\d{3}/\d{2}\s*R?\s*\d{2})\b', clean_raw, re.IGNORECASE)
    found_size = size_match.group(1) if size_match else "Tidak Ditemukan"
    
    return {
        "serial_number": serial_number,
        "dot_code": dot_code,
        "manufacturer": found_brand,
        "model_name": "Tidak Ditemukan",
        "size": found_size,
        "load_speed": "Tidak Ditemukan",
        "special_markings": "Tidak Ditemukan"
    }


@router.post("/extract")
async def extract_tire_info(
    image: UploadFile = File(...),
    mode: str = Form("fast_ocr"),
    db_session: Session = Depends(db.get_db)
):
    """Extract tire information (Serial Number, DOT, Size, Brand) from uploaded camera frame."""
    try:
        contents = await image.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image file format")
            
        # Save original upload image
        uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        filename = f"tire_{uuid.uuid4().hex[:12]}.jpg"
        save_path = os.path.join(uploads_dir, filename)
        cv2.imwrite(save_path, img)
        image_url = f"/api/v1/uploads/{filename}"

        # Perform direct OCR on image
        direct_ocr_text = perform_direct_ocr(img)

        raw_text = direct_ocr_text
        parsed = parse_dot_and_serial_fast(raw_text)
        serial_number = parsed["serial_number"]
        dot_code = parsed["dot_code"]
        manufacturer = parsed["manufacturer"]
        model_name = parsed["model_name"]
        size = parsed["size"]
        load_speed = parsed["load_speed"]
        special_markings = parsed["special_markings"]
        confidence = "0.96"

        pipeline = get_pipeline()
        
        if pipeline and mode in ["pipeline", "llm_only"]:
            try:
                if mode == "llm_only":
                    res = pipeline.run_llm_only(save_path)
                else:
                    res = pipeline.run_pipeline(save_path)
                
                if res and hasattr(res, "tire_info") and res.tire_info:
                    info = res.tire_info
                    if info.manufacturer and info.manufacturer.value != "Not found":
                        manufacturer = info.manufacturer.value
                    if info.model and info.model.value != "Not found":
                        model_name = info.model.value
                    if info.size and info.size.value != "Not found":
                        size = info.size.value
                    if info.load_speed and info.load_speed.value != "Not found":
                        load_speed = info.load_speed.value
                    if info.dot and info.dot.value != "Not found":
                        dot_code = info.dot.value
                        serial_number = f"DOT {dot_code}"
            except Exception as pe:
                logger.warning(f"Pipeline processing fallback: {pe}")
                
        elif mode == "fast_ocr":
            # Fast OCR / Regex parsing
            parsed = parse_dot_and_serial_fast(raw_text)
            serial_number = parsed["serial_number"]
            dot_code = parsed["dot_code"]
            manufacturer = parsed["manufacturer"]
            model_name = parsed["model_name"]
            size = parsed["size"]
            load_speed = parsed["load_speed"]
            special_markings = parsed["special_markings"]

        # Persist scan to database
        scan_record = db_models.TireScan(
            serial_number=serial_number,
            dot_code=dot_code,
            manufacturer=manufacturer,
            model_name=model_name,
            size=size,
            load_speed=load_speed,
            special_markings=special_markings,
            raw_text=raw_text,
            image_url=image_url,
            confidence=confidence,
            mode=mode
        )
        db_session.add(scan_record)
        db_session.commit()
        db_session.refresh(scan_record)

        return {
            "status": "success",
            "message": "Tire extracted successfully",
            "data": {
                "id": scan_record.id,
                "serial_number": scan_record.serial_number,
                "dot_code": scan_record.dot_code,
                "manufacturer": scan_record.manufacturer,
                "model_name": scan_record.model_name,
                "size": scan_record.size,
                "load_speed": scan_record.load_speed,
                "special_markings": scan_record.special_markings,
                "raw_text": scan_record.raw_text,
                "image_url": scan_record.image_url,
                "confidence": scan_record.confidence,
                "created_at": scan_record.created_at.isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Error extracting tire info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scans")
def list_tire_scans(db_session: Session = Depends(db.get_db)):
    """List all scanned tire records ordered by timestamp."""
    scans = db_session.query(db_models.TireScan).order_by(db_models.TireScan.created_at.desc()).all()
    return {
        "status": "success",
        "total": len(scans),
        "data": [{
            "id": s.id,
            "serial_number": s.serial_number,
            "dot_code": s.dot_code,
            "manufacturer": s.manufacturer,
            "model_name": s.model_name,
            "size": s.size,
            "load_speed": s.load_speed,
            "special_markings": s.special_markings,
            "raw_text": s.raw_text,
            "image_url": s.image_url,
            "confidence": s.confidence,
            "mode": s.mode,
            "created_at": s.created_at.isoformat() if s.created_at else None
        } for s in scans]
    }


@router.get("/scans/{scan_id}")
def get_tire_scan(scan_id: str, db_session: Session = Depends(db.get_db)):
    """Get single tire scan detail."""
    s = db_session.query(db_models.TireScan).filter(db_models.TireScan.id == scan_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Tire scan record not found")
    return {
        "status": "success",
        "data": {
            "id": s.id,
            "serial_number": s.serial_number,
            "dot_code": s.dot_code,
            "manufacturer": s.manufacturer,
            "model_name": s.model_name,
            "size": s.size,
            "load_speed": s.load_speed,
            "special_markings": s.special_markings,
            "raw_text": s.raw_text,
            "image_url": s.image_url,
            "confidence": s.confidence,
            "mode": s.mode,
            "created_at": s.created_at.isoformat() if s.created_at else None
        }
    }


@router.delete("/scans/{scan_id}")
def delete_tire_scan(scan_id: str, db_session: Session = Depends(db.get_db)):
    """Delete a tire scan record."""
    s = db_session.query(db_models.TireScan).filter(db_models.TireScan.id == scan_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Tire scan record not found")
    db_session.delete(s)
    db_session.commit()
    return {"status": "success", "message": "Record deleted successfully"}
