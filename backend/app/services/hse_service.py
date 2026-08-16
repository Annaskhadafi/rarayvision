import io
import time
import base64
import json
import numpy as np
import cv2
from PIL import Image

try:
    import supervision as sv
except ImportError:
    sv = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

_model_cache = {}

def get_yolo_model(model_name: str = "yolov8n"):
    """Fetch or load a cached YOLO model instance."""
    if YOLO is None:
        return None
    if model_name not in _model_cache:
        try:
            _model_cache[model_name] = YOLO(f"{model_name}.pt")
        except Exception as e:
            print(f"[HSEService] Error loading model {model_name}: {e}")
            if "yolov8n" not in _model_cache:
                _model_cache["yolov8n"] = YOLO("yolov8n.pt")
            return _model_cache["yolov8n"]
    return _model_cache.get(model_name)

def _image_bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
    """Convert raw image or video bytes to OpenCV BGR numpy array."""
    try:
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:
        # If PIL fails, attempt reading as video file via tempfile
        import tempfile
        import os
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                tmp.write(image_bytes)
                tmp_path = tmp.name

            cap = cv2.VideoCapture(tmp_path)
            frame = None
            if cap.isOpened():
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
                target_frame = max(0, total_frames // 2)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
                if not ret or frame is None:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
            cap.release()

            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

            if frame is not None:
                return frame
        except Exception as err:
            print(f"[HSEService] Video decoding error: {err}")
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        raise ValueError("File gambar atau video tidak valid / corrupt")

def _cv2_to_base64(cv2_img: np.ndarray) -> str:
    """Convert OpenCV BGR image to base64 data URI string."""
    _, buffer = cv2.imencode(".jpg", cv2_img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    b64_str = base64.b64encode(buffer).decode("utf-8")
    return f"data:image/jpeg;base64,{b64_str}"

def process_ppe_check(
    image_bytes: bytes,
    ppe_rules: dict,
    confidence: float = 0.4,
    model_name: str = "yolov8n"
) -> dict:
    """
    Evaluates PPE compliance for detected personnel in an image.
    """
    start_time = time.time()
    img_bgr = _image_bytes_to_cv2(image_bytes)
    h, w, _ = img_bgr.shape

    model = get_yolo_model(model_name)
    annotated_frame = img_bgr.copy()

    persons = []
    total_persons = 0
    violations_count = 0
    compliant_count = 0

    if model is not None:
        results = model.predict(img_bgr, conf=confidence, verbose=False)[0]
        person_idx = 1

        for box in results.boxes:
            cls_id = int(box.cls[0])
            cls_name = model.names.get(cls_id, "object").lower()

            # Filter person class (class 0 in COCO)
            if cls_name == "person" or cls_id == 0:
                total_persons += 1
                bbox = [round(float(v), 1) for v in box.xyxy[0]]
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                conf = round(float(box.conf[0]), 3)

                # Heuristic / model detection for PPE compliance
                # Upper body region for Helmet & Vest check
                person_crop = img_bgr[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                crop_h, crop_w, _ = person_crop.shape

                # Precision PPE analysis (White/Colored Hardhats & High-Vis Vests/Uniforms)
                has_helmet = True
                has_vest = True
                missing = []

                if crop_h > 20 and crop_w > 20:
                    # 1. Head / Hardhat Region Check
                    # Narrow horizontal crop (center 40% of head width) and top 18% height to isolate dome and avoid wall background
                    head_top = 0
                    head_bottom = max(1, int(crop_h * 0.18))
                    head_left = int(crop_w * 0.30)
                    head_right = int(crop_w * 0.70)

                    head_crop = person_crop[head_top:head_bottom, head_left:head_right]
                    head_h, head_w, _ = head_crop.shape

                    if head_h > 3 and head_w > 3:
                        head_hsv = cv2.cvtColor(head_crop, cv2.COLOR_BGR2HSV)
                        
                        # White Hardhat dome (Ultra High Brightness V >= 200, Low Saturation S <= 25 to avoid white walls/light bulbs)
                        mask_white_helmet = cv2.inRange(head_hsv, np.array([0, 0, 200]), np.array([180, 25, 255]))
                        # Colored Hardhats (Yellow, Orange, Red, Blue, Green: High Saturation S >= 120, High Value V >= 130)
                        mask_yellow_helmet = cv2.inRange(head_hsv, np.array([20, 120, 130]), np.array([35, 255, 255]))
                        mask_orange_helmet = cv2.inRange(head_hsv, np.array([8, 130, 130]), np.array([20, 255, 255]))
                        mask_red_helmet1 = cv2.inRange(head_hsv, np.array([0, 140, 130]), np.array([7, 255, 255]))
                        mask_red_helmet2 = cv2.inRange(head_hsv, np.array([172, 140, 130]), np.array([180, 255, 255]))
                        mask_blue_helmet = cv2.inRange(head_hsv, np.array([95, 125, 120]), np.array([125, 255, 255]))
                        mask_green_helmet = cv2.inRange(head_hsv, np.array([40, 120, 120]), np.array([85, 255, 255]))

                        total_head_px = head_h * head_w
                        pct_white = (np.count_nonzero(mask_white_helmet) / total_head_px) * 100.0
                        pct_color = ((
                            np.count_nonzero(mask_yellow_helmet) +
                            np.count_nonzero(mask_orange_helmet) +
                            np.count_nonzero(mask_red_helmet1) +
                            np.count_nonzero(mask_red_helmet2) +
                            np.count_nonzero(mask_blue_helmet) +
                            np.count_nonzero(mask_green_helmet)
                        ) / total_head_px) * 100.0
                        helmet_score = max(pct_white, pct_color)

                        if ppe_rules.get("require_helmet", True):
                            # Must cover at least 18% of the center head crop to count as a hardhat
                            if helmet_score < 18.0:
                                has_helmet = False
                                missing.append("HELMET")
                            else:
                                has_helmet = True

                    # 2. Torso / Safety Vest & Field Uniform Region Check
                    # Center 60% of torso width (20% to 80%) & height from 22% to 70% to isolate vest chest/belly
                    torso_top = int(crop_h * 0.22)
                    torso_bottom = int(crop_h * 0.70)
                    torso_left = int(crop_w * 0.20)
                    torso_right = int(crop_w * 0.80)

                    torso_crop = person_crop[torso_top:torso_bottom, torso_left:torso_right]
                    torso_h, torso_w, _ = torso_crop.shape

                    if torso_h > 3 and torso_w > 3:
                        torso_hsv = cv2.cvtColor(torso_crop, cv2.COLOR_BGR2HSV)

                        # High-Vis Lime Green / Neon Yellow Safety Vest (Hue 25..85, High Saturation S >= 90, High Value V >= 120)
                        # Excludes skin tone (which has H 0..22, S 30..110)
                        mask_hivis_green_yellow = cv2.inRange(torso_hsv, np.array([25, 90, 120]), np.array([85, 255, 255]))

                        # Safety Orange Vest (Hue 8..20, High Saturation S >= 120, High Value V >= 130)
                        # Excludes reddish/tanned skin tone (which has S < 110 or lower V)
                        mask_safety_orange = cv2.inRange(torso_hsv, np.array([8, 120, 130]), np.array([20, 255, 255]))

                        # Safety Red / High-Vis Pink-Red Vest (Hue 0..7 or 173..180, High Saturation S >= 140, High Value V >= 130)
                        mask_safety_red1 = cv2.inRange(torso_hsv, np.array([0, 140, 130]), np.array([7, 255, 255]))
                        mask_safety_red2 = cv2.inRange(torso_hsv, np.array([173, 140, 130]), np.array([180, 255, 255]))

                        # Safety Blue / Field Uniform (Hue 95..125, High Saturation S >= 125, High Value V >= 120)
                        mask_safety_blue = cv2.inRange(torso_hsv, np.array([95, 125, 120]), np.array([125, 255, 255]))

                        # Silver / White Retroreflective Stripes (Pita Reflektor K3): Low Saturation S <= 35, Ultra High Brightness V >= 190
                        mask_reflector_stripes = cv2.inRange(torso_hsv, np.array([0, 0, 190]), np.array([180, 35, 255]))

                        total_torso_px = torso_h * torso_w
                        vest_color_px = (
                            np.count_nonzero(mask_hivis_green_yellow) +
                            np.count_nonzero(mask_safety_orange) +
                            np.count_nonzero(mask_safety_red1) +
                            np.count_nonzero(mask_safety_red2) +
                            np.count_nonzero(mask_safety_blue)
                        )
                        reflector_px = np.count_nonzero(mask_reflector_stripes)

                        pct_vest_color = (vest_color_px / total_torso_px) * 100.0
                        pct_reflector = (reflector_px / total_torso_px) * 100.0

                        if ppe_rules.get("require_vest", True):
                            # Vest detected if high-vis color >= 12% OR (high-vis color >= 6% AND reflector stripes >= 3%)
                            is_vest_present = (pct_vest_color >= 12.0) or (pct_vest_color >= 6.0 and pct_reflector >= 3.0)
                            if not is_vest_present:
                                has_vest = False
                                missing.append("VEST")
                            else:
                                has_vest = True

                is_compliant = (len(missing) == 0)

                if is_compliant:
                    compliant_count += 1
                    status_str = "COMPLIANT"
                    box_color = (0, 255, 0)
                else:
                    violations_count += 1
                    status_str = "VIOLATION"
                    box_color = (0, 0, 255)

                persons.append({
                    "person_id": person_idx,
                    "bbox": bbox,
                    "confidence": conf,
                    "status": status_str,
                    "missing_ppe": missing,
                    "ppe_detected": {
                        "helmet": has_helmet,
                        "vest": has_vest
                    }
                })

                # Draw bounding box & status tag
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), box_color, 2)
                tag = f"P{person_idx}: {status_str}"
                if missing:
                    tag += f" (NO {','.join(missing)})"
                cv2.putText(annotated_frame, tag, (x1, max(20, y1 - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

                person_idx += 1

    overall_result = "PASS" if violations_count == 0 else "FAIL"
    compliance_rate = round((compliant_count / total_persons * 100.0), 1) if total_persons > 0 else 100.0

    # Banner header
    banner_color = (0, 255, 0) if overall_result == "PASS" else (0, 0, 255)
    cv2.rectangle(annotated_frame, (0, 0), (w, 40), (20, 20, 20), -1)
    cv2.putText(annotated_frame, f"HSE PPE AUDIT: {overall_result} | Personnel: {total_persons} | Violations: {violations_count}", (15, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, banner_color, 2)

    proc_time = int((time.time() - start_time) * 1000)

    return {
        "overall_result": overall_result,
        "total_persons": total_persons,
        "compliant_persons": compliant_count,
        "violations_count": violations_count,
        "compliance_rate": compliance_rate,
        "persons": persons,
        "annotated_image": _cv2_to_base64(annotated_frame),
        "processing_ms": proc_time,
        "model_used": model_name
    }

def process_danger_zone_alert(
    image_bytes: bytes,
    zones_list: list,
    confidence: float = 0.4,
    model_name: str = "yolov8n"
) -> dict:
    """
    Evaluates personnel intrusion into defined Danger Zones using Supervision PolygonZones.
    """
    start_time = time.time()
    img_bgr = _image_bytes_to_cv2(image_bytes)
    h, w, _ = img_bgr.shape

    model = get_yolo_model(model_name)
    annotated_frame = img_bgr.copy()

    intrusions = []
    has_intrusion = False

    # Perform person detection
    person_bboxes = []
    if model is not None:
        results = model.predict(img_bgr, conf=confidence, verbose=False)[0]
        for box in results.boxes:
            cls_id = int(box.cls[0])
            cls_name = model.names.get(cls_id, "").lower()
            if cls_name == "person" or cls_id == 0:
                person_bboxes.append([float(v) for v in box.xyxy[0]])

    # Evaluate each polygon zone
    for zone_cfg in zones_list:
        zone_name = zone_cfg.get("zone_name", "Danger Zone")
        pts = zone_cfg.get("polygon_points", [])
        
        if not pts or len(pts) < 3:
            continue

        np_pts = np.array(pts, np.int32).reshape((-1, 1, 2))
        
        # Use Supervision PolygonZone if available
        if sv is not None:
            poly_zone = sv.PolygonZone(polygon=np.array(pts, dtype=np.int32))
            zone_annotator = sv.PolygonZoneAnnotator(
                zone=poly_zone,
                color=sv.Color.RED if zone_cfg.get("zone_type") == "danger" else sv.Color.YELLOW,
                thickness=2
            )
            # Check how many persons inside zone
            zone_intrusions_count = 0
            for box in person_bboxes:
                foot_point = (int((box[0] + box[2]) / 2.0), int(box[3]))
                inside = cv2.pointPolygonTest(np_pts, foot_point, False) >= 0
                if inside:
                    zone_intrusions_count += 1
                    has_intrusion = True
                    intrusions.append({
                        "zone_name": zone_name,
                        "zone_type": zone_cfg.get("zone_type", "danger"),
                        "foot_point": foot_point,
                        "bbox": [round(v, 1) for v in box]
                    })
                    cv2.rectangle(annotated_frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 0, 255), 3)
                    cv2.putText(annotated_frame, f"INTRUSION: {zone_name}", (int(box[0]), max(20, int(box[1]) - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
            # Draw polygon zone
            cv2.polylines(annotated_frame, [np_pts], isClosed=True,
                          color=(0, 0, 255) if zone_cfg.get("zone_type") == "danger" else (0, 255, 255), thickness=2)
            cv2.putText(annotated_frame, f"ZONE: {zone_name} ({zone_intrusions_count})", (pts[0][0], pts[0][1] - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        else:
            # Fallback manual polygon check
            for box in person_bboxes:
                foot_point = (int((box[0] + box[2]) / 2.0), int(box[3]))
                inside = cv2.pointPolygonTest(np_pts, foot_point, False) >= 0
                if inside:
                    has_intrusion = True
                    intrusions.append({
                        "zone_name": zone_name,
                        "bbox": [round(v, 1) for v in box]
                    })
                    cv2.rectangle(annotated_frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 0, 255), 3)
            cv2.polylines(annotated_frame, [np_pts], True, (0, 0, 255), 2)

    status_str = "DANGER_ALERT" if has_intrusion else "ALL_CLEAR"
    banner_color = (0, 0, 255) if has_intrusion else (0, 255, 0)
    
    cv2.rectangle(annotated_frame, (0, 0), (w, 40), (20, 20, 20), -1)
    cv2.putText(annotated_frame, f"ZONE MONITORING: {status_str} | Intrusions: {len(intrusions)}", (15, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, banner_color, 2)

    proc_time = int((time.time() - start_time) * 1000)

    return {
        "status": status_str,
        "has_intrusion": has_intrusion,
        "intrusions_count": len(intrusions),
        "intrusions": intrusions,
        "annotated_image": _cv2_to_base64(annotated_frame),
        "processing_ms": proc_time,
        "model_used": model_name
    }

def process_near_miss_log(
    image_bytes: bytes,
    zones_list: list,
    ppe_rules: dict,
    confidence: float = 0.4,
    model_name: str = "yolov8n"
) -> dict:
    """
    Evaluates comprehensive near-miss events (Intrusion + PPE Non-compliance combined).
    """
    ppe_res = process_ppe_check(image_bytes, ppe_rules, confidence, model_name)
    zone_res = process_danger_zone_alert(image_bytes, zones_list, confidence, model_name)

    is_near_miss = (ppe_res["violations_count"] > 0) or zone_res["has_intrusion"]
    
    severity = "LOW"
    if ppe_res["violations_count"] > 0 and zone_res["has_intrusion"]:
        severity = "CRITICAL"
    elif zone_res["has_intrusion"]:
        severity = "HIGH"
    elif ppe_res["violations_count"] > 0:
        severity = "MEDIUM"

    return {
        "is_near_miss": is_near_miss,
        "severity": severity,
        "ppe_summary": {
            "total_persons": ppe_res["total_persons"],
            "violations_count": ppe_res["violations_count"]
        },
        "zone_summary": {
            "has_intrusion": zone_res["has_intrusion"],
            "intrusions_count": zone_res["intrusions_count"]
        },
        "annotated_image": zone_res["annotated_image"],
        "processing_ms": ppe_res["processing_ms"] + zone_res["processing_ms"]
    }
