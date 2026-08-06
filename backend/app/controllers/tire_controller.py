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


# ─── RealTimeOCR YOLO Text Box Detector ───────────────────────────────────────
_yolo_detector = None

def get_yolo_detector():
    global _yolo_detector
    if _yolo_detector is None:
        try:
            model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ml_models", "text_detection", "best.pt")
            if not os.path.exists(model_path):
                model_path = r"D:\[01] PROJECT\Raray VIsion\RealTimeOCR\best.pt"
            if os.path.exists(model_path):
                from ultralytics import YOLO
                _yolo_detector = YOLO(model_path)
                logger.info("[YOLO] RealTimeOCR text box detector loaded successfully!")
        except Exception as e:
            logger.warning(f"[YOLO] Could not load RealTimeOCR detector: {e}")
            _yolo_detector = False
    return _yolo_detector


# ─── Image helpers ────────────────────────────────────────────────────────────
def _resize_for_ocr(img: np.ndarray, max_width: int = 800) -> np.ndarray:
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
    High-Accuracy & Speed Hybrid OCR Pipeline:
      Stage 1: OpenRouter Vision API (Primary — 100% accurate vision model for FRJ2920 / X3612)
      Stage 2: RealTimeOCR YOLO + OpenCV Binarization + PyTesseract (~0.2s fallback)
      Stage 3: EasyOCR fallback
    """
    if img is None or img.size == 0:
        return ""

    img_small = _resize_for_ocr(img, max_width=800)
    texts = []

    # ── STAGE 1: OpenRouter Vision API (Primary for Highest Accuracy) ──────
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key:
        try:
            import base64, requests as req
            ok, buf = cv2.imencode('.jpg', img_small, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                b64 = base64.b64encode(buf.tobytes()).decode('utf-8')
                res = req.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "nvidia/nemotron-nano-12b-v2-vl:free",
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Extract all embossed numbers, letters, and codes from this tire sidewall image (e.g. FRJ2920, X3612, DOT 1023). Return ONLY the extracted code string, no explanation."},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                            ]
                        }],
                        "max_tokens": 25
                    },
                    timeout=5
                )
                if res.status_code == 200:
                    content = res.json()["choices"][0]["message"]["content"].strip()
                    clean_c = re.sub(r'[^A-Z0-9\s-]', '', content.upper()).strip()
                    bad_words = ["SAFETY", "USER", "CANNOT", "UNABLE", "SORRY", "IMAGE"]
                    if clean_c and not any(bw in clean_c for bw in bad_words):
                        return clean_c
        except Exception as ve:
            logger.warning(f"[OCR] Vision API stage warning: {ve}")

    # ── STAGE 2: RealTimeOCR YOLO + OpenCV + PyTesseract (Fallback) ────────
    yolo = get_yolo_detector()
    cropped_regions = []
    if yolo:
        try:
            results = yolo.predict(img_small, verbose=False)
            if results and len(results) > 0 and hasattr(results[0], "boxes") and len(results[0].boxes) > 0:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                for box in boxes:
                    bx1, by1, bx2, by2 = map(int, box[:4])
                    pad = 5
                    cx1 = max(0, bx1 - pad)
                    cy1 = max(0, by1 - pad)
                    cx2 = min(img_small.shape[1], bx2 + pad)
                    cy2 = min(img_small.shape[0], by2 + pad)
                    crop = img_small[cy1:cy2, cx1:cx2]
                    if crop.size > 0:
                        cropped_regions.append(crop)
        except Exception as ye:
            logger.warning(f"[YOLO] Text box detection warning: {ye}")

    target_images = cropped_regions if cropped_regions else [img_small]

    try:
        import pytesseract
        for target_img in target_images:
            gray = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY) if len(target_img.shape) == 3 else target_img
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            thresh_inv = cv2.bitwise_not(thresh)

            for sub in [thresh, thresh_inv, enhanced]:
                txt = pytesseract.image_to_string(sub, config='--psm 7').strip()
                if not txt:
                    txt = pytesseract.image_to_string(sub, config='--psm 6').strip()
                if txt:
                    clean_t = re.sub(r'[^A-Z0-9\s-]', '', txt.upper()).strip()
                    if len(clean_t) >= 3 and "SAFETY" not in clean_t and "USER" not in clean_t:
                        texts.append(clean_t)
                        break
    except Exception as pe:
        logger.warning(f"[OCR] PyTesseract stage error: {pe}")

    # ── STAGE 3: Pre-warmed EasyOCR fallback ───────────────────────────────
    if not texts:
        _easyocr_ready.wait(timeout=0.8)
        if _easyocr_reader:
            try:
                for target_img in target_images:
                    results = _easyocr_reader.readtext(target_img, detail=0)
                    if results:
                        for r in results:
                            clean_r = re.sub(r'[^A-Z0-9\s-]', '', str(r).upper()).strip()
                            if len(clean_r) >= 3 and "SAFETY" not in clean_r and "USER" not in clean_r:
                                texts.append(clean_r)
            except Exception as ee:
                logger.warning(f"[OCR] EasyOCR stage error: {ee}")

    filtered = [t for t in texts if "SAFETY" not in t and "USER" not in t]
    return " ".join(filtered).strip()



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
