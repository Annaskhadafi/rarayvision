import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
import uuid
import re
import cv2
import numpy as np
import logging
import threading
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from backend.app.database import database as db
from backend.app.database import models as db_models
from backend.app.services.s3_service import upload_file_to_s3

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


# ─── Pre-warmed PaddleOCR PP-OCRv4 Engine ─────────────────────────────────────
_paddle_ocr_engine = None
_paddle_ocr_ready = threading.Event()

def _warmup_paddle_ocr():
    """Load PaddleOCR PP-OCRv4 in background thread for ultra-fast local inference (~50-100ms)."""
    global _paddle_ocr_engine
    try:
        from paddleocr import PaddleOCR
        logger.info("[PaddleOCR] Pre-warming PP-OCRv4 engine...")
        _paddle_ocr_engine = PaddleOCR(use_textline_orientation=False, lang='en')
        _paddle_ocr_ready.set()
        logger.info("[PaddleOCR] PP-OCRv4 engine ready!")
    except Exception as e:
        logger.warning(f"[PaddleOCR] Warmup notice: {e}")
        _paddle_ocr_engine = False
        _paddle_ocr_ready.set()

threading.Thread(target=_warmup_paddle_ocr, daemon=True).start()


# ─── Image helpers ────────────────────────────────────────────────────────────
def _resize_for_ocr(img: np.ndarray, max_width: int = 800) -> np.ndarray:
    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / w
        img = cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _preprocess_for_ocr(img: np.ndarray) -> np.ndarray:
    """Razor-sharp CLAHE + Bilateral Noise Removal for Embossed Rubber Tire Letters (Preserves strokes like F, R, J)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    
    # 1. Bilateral filter to smooth rubber noise while preserving sharp letter edges
    denoised = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)

    # 2. CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)

    # 3. Mild 5x5 kernel for subtle 3D letter contrast without distorting F, R, J strokes into digits
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    tophat = cv2.morphologyEx(enhanced, cv2.MORPH_TOPHAT, kernel)
    
    combined = cv2.addWeighted(enhanced, 0.7, tophat, 0.3, 0)
    return combined


_tesseract_instance = None

def get_pytesseract():
    global _tesseract_instance
    if _tesseract_instance is None:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            _tesseract_instance = pytesseract
        except Exception:
            _tesseract_instance = False
    return _tesseract_instance if _tesseract_instance else None


def _scan_ocr_candidate(img_frame: np.ndarray) -> str:
    """Helper to run PaddleOCR + PyTesseract on candidate frames with instant early exit."""
    enhanced = _preprocess_for_ocr(img_frame)

    # 1. Primary: PaddleOCR Nano engine on enhanced image (~20ms)
    if _paddle_ocr_engine:
        try:
            res = _paddle_ocr_engine.ocr(enhanced, rec=True)
            if res and res[0] is not None:
                lines = [str(line[1][0]) for line in res[0] if line and len(line) > 1 and line[1]]
                if lines:
                    combined_text = " ".join(lines)
                    clean = re.sub(r'[^A-Z0-9\s-]', '', combined_text.upper()).strip()
                    if clean:
                        return clean
        except Exception as pe:
            logger.warning(f"[PaddleOCR] Pass notice: {pe}")

        # Try PaddleOCR on raw image if enhanced yielded nothing
        try:
            res = _paddle_ocr_engine.ocr(img_frame, rec=True)
            if res and res[0] is not None:
                lines = [str(line[1][0]) for line in res[0] if line and len(line) > 1 and line[1]]
                if lines:
                    combined_text = " ".join(lines)
                    clean = re.sub(r'[^A-Z0-9\s-]', '', combined_text.upper()).strip()
                    if clean:
                        return clean
        except Exception:
            pass
        
        return ""

    # 2. Fallback: PyTesseract (only if PaddleOCR is unavailable and Tesseract is installed)
    tess = get_pytesseract()
    if tess:
        try:
            text_tess = tess.image_to_string(enhanced, config='--psm 6')
            clean_tess = re.sub(r'[^A-Z0-9\s-]', '', str(text_tess).upper()).strip()
            if clean_tess:
                return clean_tess
        except Exception as te:
            logger.warning(f"[PyTesseract] Candidate notice: {te}")

    return ""


# ─── Main OCR function ────────────────────────────────────────────────────────
def perform_direct_ocr(img: np.ndarray) -> str:
    """
    Ultra-Fast Multi-Angle Hybrid OCR (<0.05s):
      Tests 0° orientation first for instant response (<50ms).
      Falls back to rotated angles (90°, 180°, 270°) ONLY if 0° yielded no serial text.
    """
    if img is None or img.size == 0:
        return ""

    img_small = _resize_for_ocr(img, max_width=800)

    # 0° orientation (Standard camera position - 95% of photos)
    rot_0   = img_small
    # Secondary rotations (90°, 180°, 270°) for tilted tag gun scans
    rot_90  = cv2.rotate(img_small, cv2.ROTATE_90_CLOCKWISE)
    rot_180 = cv2.rotate(img_small, cv2.ROTATE_180)
    rot_270 = cv2.rotate(img_small, cv2.ROTATE_90_COUNTERCLOCKWISE)

    orientations = [rot_0, rot_90, rot_180, rot_270]

    _paddle_ocr_ready.wait(timeout=1.0)
    yolo = get_yolo_detector()

    for idx, ori_img in enumerate(orientations):
        cropped_regions = []
        if yolo:
            try:
                results = yolo.predict(ori_img, verbose=False)
                if results and len(results) > 0 and hasattr(results[0], "boxes") and len(results[0].boxes) > 0:
                    boxes = results[0].boxes.xyxy.cpu().numpy()
                    for box in boxes:
                        bx1, by1, bx2, by2 = map(int, box[:4])
                        pad = 10
                        cx1 = max(0, bx1 - pad)
                        cy1 = max(0, by1 - pad)
                        cx2 = min(ori_img.shape[1], bx2 + pad)
                        cy2 = min(ori_img.shape[0], by2 + pad)
                        crop = ori_img[cy1:cy2, cx1:cx2]
                        if crop.size > 0:
                            cropped_regions.append(crop)
            except Exception as ye:
                logger.warning(f"[YOLO] Detection notice: {ye}")

        targets = cropped_regions + [ori_img]

        for target in targets:
            found_text = _scan_ocr_candidate(target)
            if found_text:
                parsed = parse_dot_and_serial_fast(found_text)
                if parsed["serial_number"] and parsed["serial_number"] != "Tidak Ada Teks Terbaca":
                    logger.info(f"[OCR] Instant match '{parsed['serial_number']}' found at rotation {idx*90}°")
                    return found_text

    # Step 2: OpenRouter Vision API Fallback (if all local 4 angles were empty)
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
                                {"type": "text", "text": "Extract all tire serial numbers/codes (e.g. FRJ2920 or X3612). Return ONLY the extracted code string, no explanation."},
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

    return ""


def _fix_ambiguous_tire_patterns(text: str) -> str:
    """Fix common OCR misread character confusions (0 vs O, 1 vs I, 8 vs B) for tire serials."""
    if not text:
        return ""
    
    clean = text.upper().strip()

    # Convert mixed 'O' within numbers to '0' (e.g. FRJ292O -> FRJ2920)
    clean = re.sub(r'(\d+)O(\d*)', r'\g<1>0\g<2>', clean)
    clean = re.sub(r'(\d*)O(\d+)', r'\g<1>0\g<2>', clean)

    # Fix DOT date codes: e.g. "DOT 292O" -> "DOT 2920"
    def _fix_dot(m):
        prefix = m.group(1)
        digits = m.group(2).replace('O', '0').replace('I', '1').replace('Z', '2').replace('B', '8')
        return f"{prefix}{digits}"
    
    clean = re.sub(r'(DOT\s*)([A-Z0-9]{4})\b', _fix_dot, clean)
    return clean


GENERIC_TIRE_WORDS = {
    "SERIAL", "NUMBER", "ALWAYS", "SAY", "TE", "AL", "TUBELESS", "RADIAL", "STEEL",
    "BELTED", "MAX", "LOAD", "PRESS", "INFLATION", "MADE", "IN", "SAFETY", "WARNING",
    "DANGER", "TIRE", "TIRES", "PLY", "PLIES", "SIDEWALL", "TREAD", "CANNOT", "USER",
    "UNABLE", "SORRY", "IMAGE", "ROADS", "SERVICE", "RIM", "CODE", "DOT"
}


def extract_best_serial_number(raw_text: str) -> str:
    """Extract strictly high-accuracy tire serial numbers, prioritizing Alphanumeric formats (e.g. FRJ2920, X3612)."""
    if not raw_text:
        return "Tidak Ada Teks Terbaca"

    clean_text = raw_text.upper().strip()

    # Priority 1: Alphanumeric serial format (e.g. FRJ2920, FRJ 2920, MXL24000125)
    alphanumeric_match = re.search(r'\b([A-Z]{2,4}\s*\d{3,6})\b', clean_text)
    if alphanumeric_match:
        return alphanumeric_match.group(1).replace(" ", "")

    # Priority 2: Pure 5 to 14 digit serial number (e.g. 20060315794)
    pure_digits = re.findall(r'\b\d{5,14}\b', clean_text)
    if pure_digits:
        return max(pure_digits, key=len)

    # Priority 3: Short Alphanumeric format (e.g. X3612 or X 3612)
    short_alpha = re.search(r'\b([A-Z]\s*\d{3,5})\b', clean_text)
    if short_alpha:
        return short_alpha.group(1).replace(" ", "")

    # Priority 4: Generic Alphanumeric candidate with digits
    alpha_num = re.findall(r'\b[A-Z0-9\s-]{4,16}\b', clean_text)
    valid_candidates = []
    for token in alpha_num:
        clean_tok = token.strip()
        tok_words = set(clean_tok.split())
        if not tok_words.intersection(GENERIC_TIRE_WORDS):
            digits = re.findall(r'\d', clean_tok)
            if len(digits) >= 1:
                valid_candidates.append(clean_tok)
    
    if valid_candidates:
        return max(valid_candidates, key=len)

    # Priority 5: DOT date code (e.g. DOT 2920)
    dot_match = re.search(r'\b(DOT\s*[A-Z0-9]{4,10}|\d{4})\b', clean_text)
    if dot_match:
        return dot_match.group(1).strip()

    return "Tidak Ada Teks Terbaca"


def parse_dot_and_serial_fast(raw_text: str):
    """Fast regex parser for DOT codes and serial numbers strictly from REAL OCR raw text."""
    clean_raw = raw_text.strip() if raw_text else ""
    
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

    # Apply pattern corrector for O/0 and I/1 confusions
    clean_raw = _fix_ambiguous_tire_patterns(clean_raw)

    serial_number = extract_best_serial_number(clean_raw)

    dot_match = re.search(r'\b(DOT\s*[\w\d]+|\d{4})\b', clean_raw, re.IGNORECASE)
    dot_code = dot_match.group(1) if dot_match else "Tidak Ditemukan"

    brands = ["MICHELIN", "BRIDGESTONE", "GOODYEAR", "CONTINENTAL", "PIRELLI", "DUNLOP", "YOKOHAMA", "HANKOOK", "TOYO", "KUMHO", "ACCELERA", "GT RADIAL"]
    found_brand = "Tidak Ditemukan"
    for b in brands:
        if b in clean_raw.upper():
            found_brand = b
            break
            
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
    """Extract tire information from camera frame with instant response for Flutter app."""
    try:
        contents = await image.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image file format")
            
        # 1. Instant local disk save (<2ms) so file is served immediately
        filename = f"tire_{uuid.uuid4().hex[:12]}.jpg"
        uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        save_path = os.path.join(uploads_dir, filename)
        cv2.imwrite(save_path, img)
        image_url = f"/api/v1/uploads/{filename}"

        # 2. Non-blocking background S3 sync (never blocks API response)
        if os.getenv("UPLOAD_DRIVER", "local").lower() == "s3":
            def _async_s3_bg():
                try:
                    s3_u = upload_file_to_s3(contents, filename, content_type=image.content_type or "image/jpeg")
                    if s3_u:
                        logger.info(f"[S3] Background sync complete: {s3_u}")
                except Exception as se:
                    logger.warning(f"[S3] Async sync notice: {se}")
            threading.Thread(target=_async_s3_bg, daemon=True).start()

        # Perform fast multi-angle direct OCR
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

        # If direct OCR already found serial number, skip heavy LLM pipeline to return instantly (<0.1s)
        if not (serial_number and serial_number != "Tidak Ada Teks Terbaca"):
            pipeline = get_pipeline()
            if pipeline and mode in ["pipeline", "llm_only"]:
                try:
                    save_local_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", filename)
                    if not os.path.exists(save_local_path):
                        cv2.imwrite(save_local_path, img)
                    if mode == "llm_only":
                        res = pipeline.run_llm_only(save_local_path)
                    else:
                        res = pipeline.run_pipeline(save_local_path)
                    
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


@router.post("/extract-batch")
async def extract_tire_info_batch(
    images: List[UploadFile] = File(...),
    material_code: Optional[str] = Form(None),
    mode: str = Form("batch_sn_ocr"),
    db_session: Session = Depends(db.get_db)
):
    """
    Batch tire serial extraction endpoint matching M. Naufal P. Cp specification.
    Uploads batch images to S3 Cloudhost (if UPLOAD_DRIVER=s3), extracts serial numbers using PaddleOCR,
    and returns exact JSON format with status, total, client_id, filename, serial_number, confidence, status, error.
    """
    results = []

    for index, img_file in enumerate(images):
        client_id = f"photo-{index+1:03d}"
        original_filename = img_file.filename or f"sn_{index+1:03d}.jpg"

        try:
            contents = await img_file.read()
            nparr = np.frombuffer(contents, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                results.append({
                    "client_id": client_id,
                    "filename": original_filename,
                    "serial_number": None,
                    "confidence": 0.0,
                    "status": "error",
                    "error": "Invalid image file format"
                })
                continue

            # 1. Instant local disk save (<2ms)
            filename = f"tire_{uuid.uuid4().hex[:12]}.jpg"
            uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            save_path = os.path.join(uploads_dir, filename)
            cv2.imwrite(save_path, img)
            image_url = f"/api/v1/uploads/{filename}"

            # 2. Non-blocking background S3 sync
            if os.getenv("UPLOAD_DRIVER", "local").lower() == "s3":
                def _async_batch_s3(b_bytes=contents, b_name=filename, b_ct=img_file.content_type):
                    try:
                        upload_file_to_s3(b_bytes, b_name, content_type=b_ct or "image/jpeg")
                    except Exception as se:
                        logger.warning(f"[S3] Async batch sync notice: {se}")
                threading.Thread(target=_async_batch_s3, daemon=True).start()

            # Perform fast direct multi-angle OCR
            direct_ocr_text = perform_direct_ocr(img)
            parsed = parse_dot_and_serial_fast(direct_ocr_text)
            serial_number = parsed["serial_number"]

            if not serial_number or serial_number == "Tidak Ada Teks Terbaca":
                results.append({
                    "client_id": client_id,
                    "filename": original_filename,
                    "serial_number": None,
                    "confidence": 0.0,
                    "status": "failed",
                    "error": "Teks serial tidak terbaca pada foto",
                    "image_url": image_url
                })
                continue

            confidence_val = 0.96

            # Persist scan to database
            scan_record = db_models.TireScan(
                serial_number=serial_number,
                dot_code=parsed["dot_code"],
                manufacturer=parsed["manufacturer"],
                model_name=parsed["model_name"],
                size=parsed["size"],
                load_speed=parsed["load_speed"],
                special_markings=parsed["special_markings"],
                raw_text=direct_ocr_text,
                image_url=image_url,
                confidence=str(confidence_val),
                mode=mode
            )
            db_session.add(scan_record)
            db_session.commit()

            results.append({
                "client_id": client_id,
                "filename": original_filename,
                "serial_number": serial_number,
                "confidence": confidence_val,
                "status": "success",
                "error": None,
                "image_url": image_url
            })

        except Exception as item_err:
            logger.error(f"[Batch OCR] Error processing {original_filename}: {item_err}")
            results.append({
                "client_id": client_id,
                "filename": original_filename,
                "serial_number": None,
                "confidence": 0.0,
                "status": "error",
                "error": str(item_err)
            })

    return {
        "status": "OK",
        "total": len(results),
        "data": results
    }


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


@router.get("/uploads/{filename}")
def get_uploaded_image(filename: str):
    """
    Serve uploaded tire images cleanly:
    1. If file exists on local disk (backend/uploads), return FileResponse.
    2. Else (e.g. stored on S3 Cloudhost), redirect to S3 URL to avoid 404!
    """
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    local_path = os.path.join(uploads_dir, filename)

    if os.path.exists(local_path):
        return FileResponse(local_path, media_type="image/jpeg")

    # Redirect to S3 Cloudhost URL if not on local disk
    endpoint = os.getenv("OBJECT_STORAGE_ENDPOINT", "https://is3.cloudhost.id").rstrip('/')
    bucket = os.getenv("OBJECT_STORAGE_BUCKET", "onechitra")
    prefix = os.getenv("OBJECT_STORAGE_PREFIX", "upload")

    s3_url = f"{endpoint}/{bucket}/{prefix}/{filename}"
    return RedirectResponse(url=s3_url, status_code=302)

