import os
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

# ─── Uploads Directory Helper ────────────────────────────────────────────────
def get_uploads_dir() -> str:
    """Returns absolute path to backend/uploads directory."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    uploads_dir = os.path.join(backend_dir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    return uploads_dir


# ─── Pipeline Singleton ──────────────────────────────────────────────────────
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


# ─── RapidOCR Engine Singleton (ONNX Runtime) ────────────────────────────────
_rapid_ocr_engine = None
_rapid_ocr_lock = threading.Lock()

def get_rapid_ocr():
    """Initializes RapidOCR on ONNX Runtime for ultra-fast, CPU-friendly OCR."""
    global _rapid_ocr_engine
    if _rapid_ocr_engine is None:
        with _rapid_ocr_lock:
            if _rapid_ocr_engine is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                    _rapid_ocr_engine = RapidOCR()
                    logger.info("[RapidOCR] ONNX Runtime OCR engine initialized successfully!")
                except Exception as e:
                    logger.error(f"[RapidOCR] Failed to initialize: {e}")
                    _rapid_ocr_engine = False
    return _rapid_ocr_engine if _rapid_ocr_engine else None


# Pre-warm RapidOCR in a background thread
threading.Thread(target=get_rapid_ocr, daemon=True).start()


# ─── Image Preprocessing Helpers ─────────────────────────────────────────────
def _resize_for_ocr(img: np.ndarray, max_width: int = 1280, min_height: int = 250) -> np.ndarray:
    """Smart resizer: maintains character stroke thickness for camera frames and wide strips."""
    h, w = img.shape[:2]
    # If image is a wide banner (e.g. unrolled tire sidewall where w > 2.5 * h)
    if w > 2.5 * h:
        if h < min_height:
            scale = min_height / h
            new_w = min(int(w * scale), 4800)
            return cv2.resize(img, (new_w, min_height), interpolation=cv2.INTER_LINEAR)
        elif w > 4800:
            scale = 4800 / w
            return cv2.resize(img, (4800, int(h * scale)), interpolation=cv2.INTER_AREA)
        return img

    if max(h, w) > max_dimension:
        scale = max_dimension / max(h, w)
        return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _preprocess_for_ocr(img: np.ndarray) -> np.ndarray:
    """Sharp CLAHE + Bilateral filter for embossed rubber tire sidewall text."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    denoised = cv2.bilateralFilter(gray, d=5, sigmaColor=50, sigmaSpace=50)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    tophat = cv2.morphologyEx(enhanced, cv2.MORPH_TOPHAT, kernel)
    combined = cv2.addWeighted(enhanced, 0.7, tophat, 0.3, 0)
    return combined


# ─── Tire Dictionary & Brand List ─────────────────────────────────────────────
TIRE_BRANDS = [
    "MICHELIN", "BRIDGESTONE", "GOODYEAR", "CONTINENTAL", "PIRELLI",
    "DUNLOP", "YOKOHAMA", "HANKOOK", "TOYO", "KUMHO", "ACCELERA",
    "GT RADIAL", "GAJAH TUNGGAL", "NEXEN", "SAILUN", "AEOLUS",
    "DOUBLE COIN", "TRIANGLE", "LINGLONG", "CHAO YANG", "FORCEUM",
    "ACHILLES", "EP TYRES", "KENDA", "MAXXIS", "COOPER", "FALKEN",
    "FIRESTONE", "NOKIAN", "SUMITOMO", "GENERAL TIRE", "BFGOODRICH",
    "DELIUM", "CORSA", "SWALLOW", "FDR", "IRC"
]

GENERIC_TIRE_WORDS = {
    "SERIAL", "NUMBER", "ALWAYS", "SAY", "TE", "AL", "TUBELESS", "RADIAL", "STEEL",
    "BELTED", "MAX", "LOAD", "PRESS", "INFLATION", "MADE", "IN", "SAFETY", "WARNING",
    "DANGER", "TIRE", "TIRES", "PLY", "PLIES", "SIDEWALL", "TREAD", "CANNOT", "USER",
    "UNABLE", "SORRY", "IMAGE", "ROADS", "SERVICE", "RIM", "CODE", "DOT"
}


# ─── Direct Multi-Angle OCR with Real-Time Detections ─────────────────────────
def perform_direct_ocr(img: np.ndarray):
    """
    Runs RapidOCR (ONNX Runtime) multi-angle detection.
    Returns:
        tuple (combined_text: str, detections: List[dict])
        Each detection is {
            "box": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
            "norm_box": [[nx1, ny1], [nx2, ny2], [nx3, ny3], [nx4, ny4]],
            "text": str,
            "score": float
        }
    """
    if img is None or img.size == 0:
        return "", []

    orig_h, orig_w = img.shape[:2]
    img_small = _resize_for_ocr(img, max_width=800)
    small_h, small_w = img_small.shape[:2]

    engine = get_rapid_ocr()
    if not engine:
        return "", []

    orientations = [
        (img_small, 0),
        (cv2.rotate(img_small, cv2.ROTATE_90_CLOCKWISE), 90),
        (cv2.rotate(img_small, cv2.ROTATE_180), 180),
        (cv2.rotate(img_small, cv2.ROTATE_90_COUNTERCLOCKWISE), 270)
    ]

    best_combined_text = ""
    best_detections = []

    for ori_img, angle in orientations:
        cur_h, cur_w = ori_img.shape[:2]
        try:
            res, _ = engine(ori_img)
        except Exception as e:
            logger.warning(f"[RapidOCR] Inference error at {angle}°: {e}")
            res = None

        if res and len(res) > 0:
            cur_detections = []
            cur_texts = []
            for item in res:
                if not item or len(item) < 2:
                    continue
                pts = item[0]
                text = str(item[1]).strip()
                score = round(float(item[2]), 3) if len(item) > 2 else 0.95

                if not text:
                    continue

                cur_texts.append(text)

                # Normalized coordinates (0.0 to 1.0)
                norm_pts = [[round(p[0] / cur_w, 4), round(p[1] / cur_h, 4)] for p in pts]

                # Map back to original frame coordinates if angle is 0
                if angle == 0:
                    scale_x = orig_w / small_w
                    scale_y = orig_h / small_h
                    orig_pts = [[round(p[0] * scale_x, 1), round(p[1] * scale_y, 1)] for p in pts]
                else:
                    orig_pts = [[round(p[0], 1), round(p[1], 1)] for p in pts]

                cur_detections.append({
                    "box": orig_pts,
                    "norm_box": norm_pts,
                    "text": text,
                    "score": score
                })

            combined = " ".join(cur_texts)
            parsed = parse_dot_and_serial_fast(combined)

            # Check if this orientation detected high-value tire information
            if (parsed["serial_number"] != "Tidak Ada Teks Terbaca" or
                parsed["manufacturer"] != "Tidak Ditemukan" or
                parsed["size"] != "Tidak Ditemukan" or
                parsed["dot_code"] != "Tidak Ditemukan"):
                logger.info(f"[RapidOCR] Match found at {angle}°: {parsed['serial_number']} | {parsed['manufacturer']}")
                return combined, cur_detections

            if len(cur_detections) > len(best_detections):
                best_combined_text = combined
                best_detections = cur_detections

    # Fallback to OpenRouter Vision API if local OCR yielded no detections and key is configured
    if not best_combined_text:
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if openrouter_key:
            try:
                import base64, requests as req
                ok, buf = cv2.imencode('.jpg', img_small, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    b64 = base64.b64encode(buf.tobytes()).decode('utf-8')
                    model_to_use = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")
                    res = req.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {openrouter_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": model_to_use,
                            "messages": [{
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Extract all tire text, brand, size, and DOT/serial codes. Return ONLY the detected text."},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                                ]
                            }],
                            "max_tokens": 50
                        },
                        timeout=5
                    )
                    if res.status_code == 200:
                        content = res.json()["choices"][0]["message"]["content"].strip()
                        clean_c = re.sub(r'[^A-Z0-9\s/-]', '', content.upper()).strip()
                        bad_words = ["SAFETY", "USER", "CANNOT", "UNABLE", "SORRY", "IMAGE"]
                        if clean_c and not any(bw in clean_c for bw in bad_words):
                            return clean_c, []
            except Exception as ve:
                logger.warning(f"[OCR] Vision API fallback warning: {ve}")

    return best_combined_text, best_detections


# ─── Ambiguity & Pattern Fixer ───────────────────────────────────────────────
def _fix_ambiguous_tire_patterns(text: str) -> str:
    """Fix common OCR misread character confusions (0 vs O, 1 vs I, 8 vs B) for tire serials."""
    if not text:
        return ""
    clean = text.upper().strip()
    clean = re.sub(r'(\d+)O(\d*)', r'\g<1>0\g<2>', clean)
    clean = re.sub(r'(\d*)O(\d+)', r'\g<1>0\g<2>', clean)

    def _fix_dot(m):
        prefix = m.group(1)
        digits = m.group(2).replace('O', '0').replace('I', '1').replace('Z', '2').replace('B', '8')
        return f"{prefix}{digits}"

    clean = re.sub(r'(DOT\s*)([A-Z0-9]{4})\b', _fix_dot, clean)
    return clean


# ─── Serial Number Extractor ─────────────────────────────────────────────────
def extract_best_serial_number(raw_text: str, size: str = "") -> str:
    """Extract strictly high-accuracy tire serial numbers or DOT date codes."""
    if not raw_text:
        return "Tidak Ada Teks Terbaca"

    clean_text = raw_text.upper().strip()

    # Clean out markings and size fragments that might produce false positive serial numbers
    scrubbed = re.sub(r'M\+S\s*', ' ', clean_text)
    scrubbed = re.sub(r'M/S\s*', ' ', scrubbed)
    if size and size != "Tidak Ditemukan":
        scrubbed = scrubbed.replace(size, ' ')
        for part in re.split(r'[/R\s-]+', size):
            if part:
                scrubbed = re.sub(rf'\b{part}\b', ' ', scrubbed)
    scrubbed = re.sub(r'\s+', ' ', scrubbed).strip()

    # Priority 1: Alphanumeric serial with letters + digits (e.g. 140E7402504, FRJ2920, MXL24000125)
    alpha_num_long = re.findall(r'\b(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{6,16}\b', scrubbed)
    if alpha_num_long:
        candidates = [c for c in alpha_num_long if not c.startswith("DOT")]
        if candidates:
            return max(candidates, key=len)

    # Priority 2: Pure 5 to 14 digit serial number (e.g. 20060315794, 092020)
    pure_digits = re.findall(r'\b\d{5,14}\b', scrubbed)
    if pure_digits:
        return max(pure_digits, key=len)

    # Priority 3: Standard embossed 2-4 letters + 3-6 digits (e.g. FRJ2920, AB1234)
    alphanumeric_match = re.search(r'\b([A-Z]{2,4}\s*\d{3,6})\b', scrubbed)
    if alphanumeric_match:
        return alphanumeric_match.group(1).replace(" ", "")

    # Priority 4: Short Alphanumeric format (e.g. X3612 or X 3612)
    short_alpha = re.search(r'\b([A-Z]\s*\d{3,5})\b', scrubbed)
    if short_alpha:
        return short_alpha.group(1).replace(" ", "")

    # Priority 5: DOT serial / date code (e.g. DOT 03SHBCA419 or DOT 2920)
    dot_match = re.search(r'\bDOT\s*([A-Z0-9\s]{4,14})\b', clean_text)
    if dot_match:
        dot_val = dot_match.group(1).strip()
        tokens = dot_val.split()
        if tokens:
            return f"DOT {tokens[-1]}"
        return f"DOT {dot_val}"

    # Priority 6: 4-digit date code following DOT pattern (e.g. 2920, 2420)
    date_codes = re.findall(r'\b([0-5]\d[12]\d)\b', scrubbed)
    if date_codes:
        return f"DOT {date_codes[0]}"

    return "Tidak Ada Teks Terbaca"


# ─── Structured Tire Parser ──────────────────────────────────────────────────
def parse_dot_and_serial_fast(raw_text: str):
    """Fast regex parser for DOT codes, serial numbers, brand, size, speed index."""
    clean_raw = raw_text.strip() if raw_text else ""
    if "user safety" in clean_raw.lower() or "safety warning" in clean_raw.lower():
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

    clean_raw = _fix_ambiguous_tire_patterns(clean_raw)

    # 1. Tire Size (Passenger, Light Truck, Commercial Truck)
    size_match = re.search(
        r'\b(\d{2,3}/\d{2}\s*R?\s*\d{2}(?:\.5)?|\d{1,2}(?:\.\d{1,2})?\s*(?:R|-)\s*\d{2}(?:\.5)?|\d{3}\s*R\s*\d{2})\b',
        clean_raw,
        re.IGNORECASE
    )
    found_size = size_match.group(1).replace(" ", "") if size_match else "Tidak Ditemukan"

    # 2. Serial Number
    serial_number = extract_best_serial_number(clean_raw, found_size)

    # 3. DOT Code (supports "DOT ...", "DOT1234...", etc.)
    dot_match = re.search(r'\bDOT\s*([A-Z0-9]{4,12}(?:\s+[A-Z0-9]{2,6})*)\b', clean_raw, re.IGNORECASE)
    if dot_match:
        dot_code = f"DOT {dot_match.group(1).strip()}"
    else:
        dot_direct = re.search(r'\bDOT([A-Z0-9]{4,12})\b', clean_raw, re.IGNORECASE)
        if dot_direct:
            dot_code = f"DOT {dot_direct.group(1).strip()}"
        else:
            date_m = re.search(r'\b([0-5]\d[12]\d)\b', clean_raw)
            dot_code = f"DOT {date_m.group(1)}" if date_m else "Tidak Ditemukan"

    # 2. Manufacturer / Brand
    found_brand = "Tidak Ditemukan"
    clean_upper = clean_raw.upper()
    for b in TIRE_BRANDS:
        if b in clean_upper:
            found_brand = b
            break


    # 4. Load & Speed Index (e.g. 91V, 94W, 154/150K)
    speed_match = re.search(r'\b(\d{2,3}(?:/\d{2,3})?\s*[H-Z])\b', clean_raw)
    load_speed = speed_match.group(1).strip() if speed_match else "Tidak Ditemukan"

    # 5. Special Markings (M+S, TUBELESS, RADIAL, XL)
    special_markings_list = []
    if "M+S" in clean_upper or "M/S" in clean_upper or "M & S" in clean_upper:
        special_markings_list.append("M+S")
    if "TUBELESS" in clean_upper:
        special_markings_list.append("TUBELESS")
    if "RADIAL" in clean_upper:
        special_markings_list.append("RADIAL")
    if "EXTRA LOAD" in clean_upper or re.search(r'\bXL\b', clean_upper):
        special_markings_list.append("XL")
    if "RUN FLAT" in clean_upper or "RFT" in clean_upper:
        special_markings_list.append("RUN FLAT")

    special_markings = ", ".join(special_markings_list) if special_markings_list else "Tidak Ditemukan"

    return {
        "serial_number": serial_number,
        "dot_code": dot_code,
        "manufacturer": found_brand,
        "model_name": "Tidak Ditemukan",
        "size": found_size,
        "load_speed": load_speed,
        "special_markings": special_markings
    }


# ─── Main Extraction API Endpoint ─────────────────────────────────────────────
@router.post("/extract")
async def extract_tire_info(
    image: UploadFile = File(...),
    mode: str = Form("fast_ocr"),
    db_session: Session = Depends(db.get_db)
):
    """
    Extract tire sidewall information using RapidOCR with real-time detection feedback.
    Saves to database only if valid tire properties are detected or if snapshot is manual/upload.
    """
    try:
        contents = await image.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image file format")

        # 1. Instant local disk save in backend/uploads
        filename = f"tire_{uuid.uuid4().hex[:12]}.jpg"
        uploads_dir = get_uploads_dir()
        save_path = os.path.join(uploads_dir, filename)
        cv2.imwrite(save_path, img)
        image_url = f"/api/v1/uploads/{filename}"

        # 2. Non-blocking background S3 sync (if configured)
        if os.getenv("UPLOAD_DRIVER", "local").lower() == "s3":
            def _async_s3_bg():
                try:
                    s3_u = upload_file_to_s3(contents, filename, content_type=image.content_type or "image/jpeg")
                    if s3_u:
                        logger.info(f"[S3] Background sync complete: {s3_u}")
                except Exception as se:
                    logger.warning(f"[S3] Async sync notice: {se}")
            threading.Thread(target=_async_s3_bg, daemon=True).start()

        # 3. Perform RapidOCR multi-angle extraction
        raw_text, detections = perform_direct_ocr(img)
        parsed = parse_dot_and_serial_fast(raw_text)

        serial_number = parsed["serial_number"]
        dot_code = parsed["dot_code"]
        manufacturer = parsed["manufacturer"]
        model_name = parsed["model_name"]
        size = parsed["size"]
        load_speed = parsed["load_speed"]
        special_markings = parsed["special_markings"]
        confidence = "0.98"

        # Check if meaningful tire information was found
        has_real_info = (
            (serial_number and serial_number != "Tidak Ada Teks Terbaca") or
            (manufacturer and manufacturer != "Tidak Ditemukan") or
            (size and size != "Tidak Ditemukan") or
            (dot_code and dot_code != "Tidak Ditemukan")
        )

        # Skip database spamming during continuous live auto-scan if nothing was found
        should_save = has_real_info or (mode in ["manual", "upload", "pipeline", "llm_only"])

        scan_record_id = None
        created_at_str = None

        if should_save:
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
            scan_record_id = scan_record.id
            created_at_str = scan_record.created_at.isoformat() if scan_record.created_at else None

        return {
            "status": "success",
            "message": "Tire extracted successfully" if has_real_info else "Frame processed (no tire detected)",
            "data": {
                "id": scan_record_id,
                "serial_number": serial_number,
                "dot_code": dot_code,
                "manufacturer": manufacturer,
                "model_name": model_name,
                "size": size,
                "load_speed": load_speed,
                "special_markings": special_markings,
                "raw_text": raw_text,
                "image_url": image_url,
                "confidence": confidence,
                "detections": detections,
                "created_at": created_at_str,
                "saved": should_save
            }
        }
    except Exception as e:
        logger.error(f"Error extracting tire info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Batch Extraction Endpoint ────────────────────────────────────────────────
@router.post("/extract-batch")
async def extract_tire_info_batch(
    images: List[UploadFile] = File(...),
    material_code: Optional[str] = Form(None),
    mode: str = Form("batch_sn_ocr"),
    db_session: Session = Depends(db.get_db)
):
    """Batch tire serial extraction endpoint."""
    results = []
    uploads_dir = get_uploads_dir()

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

            filename = f"tire_{uuid.uuid4().hex[:12]}.jpg"
            save_path = os.path.join(uploads_dir, filename)
            cv2.imwrite(save_path, img)
            image_url = f"/api/v1/uploads/{filename}"

            if os.getenv("UPLOAD_DRIVER", "local").lower() == "s3":
                def _async_batch_s3(b_bytes=contents, b_name=filename, b_ct=img_file.content_type):
                    try:
                        upload_file_to_s3(b_bytes, b_name, content_type=b_ct or "image/jpeg")
                    except Exception as se:
                        logger.warning(f"[S3] Async batch sync notice: {se}")
                threading.Thread(target=_async_batch_s3, daemon=True).start()

            raw_text, detections = perform_direct_ocr(img)
            parsed = parse_dot_and_serial_fast(raw_text)
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

            confidence_val = 0.98

            scan_record = db_models.TireScan(
                serial_number=serial_number,
                dot_code=parsed["dot_code"],
                manufacturer=parsed["manufacturer"],
                model_name=parsed["model_name"],
                size=parsed["size"],
                load_speed=parsed["load_speed"],
                special_markings=parsed["special_markings"],
                raw_text=raw_text,
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


# ─── Scans History Endpoints ──────────────────────────────────────────────────
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


@router.delete("/scans/clear-empty")
def clear_empty_scans(db_session: Session = Depends(db.get_db)):
    """Delete all tire scans where no serial or valid text was extracted."""
    deleted = db_session.query(db_models.TireScan).filter(
        (db_models.TireScan.serial_number == "Tidak Ada Teks Terbaca") |
        (db_models.TireScan.serial_number == None) |
        (db_models.TireScan.serial_number == "")
    ).delete(synchronize_session=False)
    db_session.commit()
    return {
        "status": "success",
        "message": f"Berhasil menghapus {deleted} data log kosong",
        "deleted_count": deleted
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


# ─── Image Serving with S3 Fallback ──────────────────────────────────────────
@router.get("/uploads/{filename}")
def get_uploaded_image(filename: str):
    """
    Serve uploaded tire images cleanly:
    1. If file exists on local disk (backend/uploads or backend/app/uploads), return FileResponse.
    2. Else (e.g. stored on S3 Cloudhost), redirect to S3 URL to avoid 404!
    """
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    uploads_dir = os.path.join(backend_dir, "uploads")
    local_path = os.path.join(uploads_dir, filename)

    if os.path.exists(local_path):
        return FileResponse(local_path, media_type="image/jpeg")

    alt_path = os.path.join(backend_dir, "app", "uploads", filename)
    if os.path.exists(alt_path):
        return FileResponse(alt_path, media_type="image/jpeg")

    endpoint = os.getenv("OBJECT_STORAGE_ENDPOINT", "https://is3.cloudhost.id").rstrip('/')
    bucket = os.getenv("OBJECT_STORAGE_BUCKET", "onechitra")
    prefix = os.getenv("OBJECT_STORAGE_PREFIX", "upload")

    s3_url = f"{endpoint}/{bucket}/{prefix}/{filename}"
    return RedirectResponse(url=s3_url, status_code=302)
