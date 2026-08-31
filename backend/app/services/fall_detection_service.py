import os
import sys
import io
import time
import uuid
import math
import base64
import numpy as np
import cv2
from PIL import Image
from typing import Dict, Any, List, Optional, Tuple

# Mock tensorflow modules on Windows if needed to prevent DLL loading error in mediapipe
if "tensorflow" not in sys.modules:
    import types
    tf = types.ModuleType("tensorflow")
    tf_tools = types.ModuleType("tensorflow.tools")
    tf_docs = types.ModuleType("tensorflow.tools.docs")
    tf_dc = types.ModuleType("tensorflow.tools.docs.doc_controls")
    tf_dc.do_not_generate_docs = lambda x: x
    tf_docs.doc_controls = tf_dc
    tf_tools.docs = tf_docs
    tf.tools = tf_tools
    sys.modules["tensorflow"] = tf
    sys.modules["tensorflow.tools"] = tf_tools
    sys.modules["tensorflow.tools.docs"] = tf_docs
    sys.modules["tensorflow.tools.docs.doc_controls"] = tf_dc

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

_detector_instance = None
_model_path = None

def _get_model_path() -> str:
    global _model_path
    if _model_path and os.path.exists(_model_path):
        return _model_path

    # Check potential model locations
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, "..", "..", "pose_landmarker_lite.task"),
        os.path.join(current_dir, "..", "..", "..", "pose_landmarker_lite.task"),
        os.path.join(current_dir, "models", "pose_landmarker_lite.task"),
        "pose_landmarker_lite.task"
    ]
    for p in candidates:
        abs_p = os.path.abspath(p)
        if os.path.exists(abs_p):
            _model_path = abs_p
            return _model_path

    # If not found, download automatically
    target_path = os.path.abspath(candidates[0])
    try:
        import urllib.request
        url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        print(f"[FallDetectionService] Downloading model to {target_path}...")
        urllib.request.urlretrieve(url, target_path)
        _model_path = target_path
        return _model_path
    except Exception as e:
        print(f"[FallDetectionService] Error downloading model: {e}")
        return "pose_landmarker_lite.task"

def get_pose_detector():
    """Initializes and returns cached singleton MediaPipe PoseLandmarker."""
    global _detector_instance
    if _detector_instance is not None:
        return _detector_instance

    model_file = _get_model_path()
    try:
        base_options = python.BaseOptions(model_asset_path=model_file)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_poses=4,  # Detect up to 4 people simultaneously
            min_pose_detection_confidence=0.35,
            min_pose_presence_confidence=0.35,
            min_tracking_confidence=0.35,
            output_segmentation_masks=False
        )
        _detector_instance = vision.PoseLandmarker.create_from_options(options)
        print("[FallDetectionService] MediaPipe Pose Landmarker successfully initialized.")
    except Exception as err:
        print(f"[FallDetectionService] Failed to initialize PoseLandmarker: {err}")
        _detector_instance = None

    return _detector_instance

# Landmark connections for skeleton rendering
POSE_CONNECTIONS = [
    (11, 12),  # Shoulders
    (11, 13), (13, 15),  # Left Arm
    (12, 14), (14, 16),  # Right Arm
    (11, 23), (12, 24),  # Torso sides
    (23, 24),  # Hips
    (23, 25), (25, 27),  # Left Leg
    (24, 26), (26, 28),  # Right Leg
    (27, 31), (28, 32),  # Feet
    (0, 1), (1, 2), (2, 3), (3, 7),  # Left face
    (0, 4), (4, 5), (5, 6), (6, 8),  # Right face
    (9, 10)  # Mouth
]

def calculate_angle(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """
    Calculates angle of line (p1 -> p2) with respect to horizontal axis.
    Returns angle in degrees (0 to 90 degrees).
    """
    dx = abs(p2[0] - p1[0])
    dy = abs(p2[1] - p1[1])
    if dx == 0 and dy == 0:
        return 90.0
    angle_rad = math.atan2(dy, dx)
    return math.degrees(angle_rad)

def _image_bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
    """Decodes image bytes to OpenCV BGR frame."""
    pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

def _cv2_to_base64(cv2_img: np.ndarray) -> str:
    """Encodes OpenCV BGR frame to JPEG base64 data URI."""
    _, buffer = cv2.imencode(".jpg", cv2_img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    b64_str = base64.b64encode(buffer).decode("utf-8")
    return f"data:image/jpeg;base64,{b64_str}"

def analyze_pose_landmarks(
    landmarks,
    img_w: int,
    img_h: int,
    angle_threshold: float = 45.0,
    ratio_threshold: float = 1.05
) -> Dict[str, Any]:
    """
    Analyzes single-person pose landmarks:
    - Calculates torso angle (mid-shoulder to mid-hip)
    - Computes bounding box and aspect ratio (width / height)
    - Determines classification: NORMAL | WARNING | FALLEN
    """
    pts = []
    for lm in landmarks:
        pts.append((lm.x * img_w, lm.y * img_h, lm.visibility))

    xs = [p[0] for p in pts if p[2] > 0.2]
    ys = [p[1] for p in pts if p[2] > 0.2]

    if not xs or not ys:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

    min_x, max_x = max(0, int(min(xs))), min(img_w, int(max(xs)))
    min_y, max_y = max(0, int(min(ys))), min(img_h, int(max(ys)))

    bbox_w = max(1, max_x - min_x)
    bbox_h = max(1, max_y - min_y)
    aspect_ratio = round(bbox_w / bbox_h, 2)

    # Landmark indices:
    # 11: Left Shoulder, 12: Right Shoulder
    # 23: Left Hip, 24: Right Hip
    left_shoulder = pts[11]
    right_shoulder = pts[12]
    left_hip = pts[23]
    right_hip = pts[24]

    # Midpoints
    mid_shoulder = (
        (left_shoulder[0] + right_shoulder[0]) / 2.0,
        (left_shoulder[1] + right_shoulder[1]) / 2.0
    )
    mid_hip = (
        (left_hip[0] + right_hip[0]) / 2.0,
        (left_hip[1] + right_hip[1]) / 2.0
    )

    # Torso inclination with horizontal ground (0 = lying flat, 90 = vertical)
    torso_angle = round(calculate_angle(mid_shoulder, mid_hip), 1)

    # Also check head to hip angle if shoulders are occluded
    nose = pts[0]
    head_hip_angle = round(calculate_angle(nose[:2], mid_hip), 1)

    # Evaluate Fall Detection Kinematics
    # Standing person: torso angle > 65 deg, aspect_ratio < 0.85
    # Fallen person: torso angle < 45 deg OR (torso angle < 52 deg AND aspect ratio > 1.0)
    is_fallen = False
    is_warning = False

    if (torso_angle < angle_threshold) or (aspect_ratio >= ratio_threshold and torso_angle < (angle_threshold + 12.0)):
        is_fallen = True
        status = "FALLEN"
    elif torso_angle < 60.0 or aspect_ratio >= 0.85:
        is_warning = True
        status = "WARNING"
    else:
        status = "NORMAL"

    confidence = round(float(np.mean([lm.visibility for lm in landmarks if lm.visibility > 0.1])), 2)

    return {
        "status": status,
        "is_fallen": is_fallen,
        "is_warning": is_warning,
        "torso_angle": torso_angle,
        "head_hip_angle": head_hip_angle,
        "aspect_ratio": aspect_ratio,
        "confidence": confidence,
        "bbox": [min_x, min_y, max_x, max_y],
        "mid_shoulder": [round(mid_shoulder[0]), round(mid_shoulder[1])],
        "mid_hip": [round(mid_hip[0]), round(mid_hip[1])],
        "points": [(round(p[0]), round(p[1])) for p in pts]
    }

def draw_fall_annotation(
    frame: np.ndarray,
    person_data_list: List[Dict[str, Any]],
    fps: float = 0.0
) -> np.ndarray:
    """Draws skeleton, bounding boxes, posture telemetry and HUD alert overlay."""
    annotated = frame.copy()
    h, w, _ = annotated.shape

    any_fallen = any(p["is_fallen"] for p in person_data_list)
    any_warning = any(p["is_warning"] for p in person_data_list)

    # Draw each detected person
    for idx, p in enumerate(person_data_list):
        status = p["status"]
        bbox = p["bbox"]
        pts = p["points"]

        if status == "FALLEN":
            color = (0, 0, 255)      # Red BGR
            status_text = "FALL DETECTED!"
        elif status == "WARNING":
            color = (0, 215, 255)    # Amber/Yellow
            status_text = "WARNING (SITTING/BENDING)"
        else:
            color = (0, 255, 0)      # Green
            status_text = "NORMAL (STANDING)"

        # Draw skeleton connections
        for conn in POSE_CONNECTIONS:
            pt1_idx, pt2_idx = conn
            if pt1_idx < len(pts) and pt2_idx < len(pts):
                pt1 = pts[pt1_idx]
                pt2 = pts[pt2_idx]
                # Filter out zero coordinates
                if pt1[0] > 0 and pt1[1] > 0 and pt2[0] > 0 and pt2[1] > 0:
                    cv2.line(annotated, pt1, pt2, color, 2, cv2.LINE_AA)

        # Draw landmark joints
        for pt in pts:
            if pt[0] > 0 and pt[1] > 0:
                cv2.circle(annotated, pt, 4, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(annotated, pt, 3, color, -1, cv2.LINE_AA)

        # Draw torso vector (mid-shoulder to mid-hip)
        s_mid = tuple(p["mid_shoulder"])
        h_mid = tuple(p["mid_hip"])
        cv2.line(annotated, s_mid, h_mid, (255, 255, 0), 3, cv2.LINE_AA)

        # Draw Bounding Box
        x1, y1, x2, y2 = bbox
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        # Label badge
        badge_text = f"P{idx+1}: {status_text} | {p['torso_angle']}\u00b0 | AR:{p['aspect_ratio']}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 1
        (tw, th), baseline = cv2.getTextSize(badge_text, font, font_scale, thickness)

        bg_y1 = max(0, y1 - th - 10)
        bg_y2 = max(th + 10, y1)
        cv2.rectangle(annotated, (x1, bg_y1), (x1 + tw + 10, bg_y2), color, -1)
        cv2.putText(
            annotated,
            badge_text,
            (x1 + 5, bg_y2 - 5),
            font,
            font_scale,
            (0, 0, 0) if status != "FALLEN" else (255, 255, 255),
            thickness,
            cv2.LINE_AA
        )

    # Top HUD Banner
    hud_h = 50
    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (w, hud_h), (20, 24, 33), -1)
    cv2.addWeighted(overlay, 0.85, annotated, 0.15, 0, annotated)

    # Status icon & text on HUD
    if any_fallen:
        hud_bg = (0, 0, 220)
        cv2.rectangle(annotated, (0, 0), (w, hud_h), hud_bg, -1)
        hud_title = "CRITICAL ALERT: PERSON FALL DETECTED!"
        title_color = (255, 255, 255)
    elif any_warning:
        hud_title = "SAFETY MONITOR: WARNING (BENDING / CROUCHED)"
        title_color = (0, 220, 255)
    else:
        hud_title = "SAFETY MONITOR: ALL NORMAL (SAFE)"
        title_color = (0, 255, 0)

    cv2.putText(annotated, hud_title, (16, 32), cv2.FONT_HERSHEY_DUPLEX, 0.7, title_color, 2, cv2.LINE_AA)

    # Telemetry info on right side
    telemetry_str = f"Persons: {len(person_data_list)}"
    if fps > 0:
        telemetry_str += f" | {fps:.1f} FPS"
    cv2.putText(annotated, telemetry_str, (w - 220, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1, cv2.LINE_AA)

    return annotated

def process_fall_frame(
    image_bytes: bytes,
    angle_threshold: float = 45.0,
    ratio_threshold: float = 1.05
) -> Dict[str, Any]:
    """Processes a single camera frame or snapshot for fall detection."""
    start_time = time.time()
    detector = get_pose_detector()
    if detector is None:
        raise RuntimeError("MediaPipe Pose detector could not be initialized")

    frame_bgr = _image_bytes_to_cv2(image_bytes)
    h, w, _ = frame_bgr.shape

    # Convert BGR to RGB for MediaPipe
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

    # Run inference
    detection_result = detector.detect(mp_image)

    person_data_list = []
    if detection_result and detection_result.pose_landmarks:
        for landmarks in detection_result.pose_landmarks:
            analysis = analyze_pose_landmarks(
                landmarks,
                img_w=w,
                img_h=h,
                angle_threshold=angle_threshold,
                ratio_threshold=ratio_threshold
            )
            person_data_list.append(analysis)

    elapsed_ms = round((time.time() - start_time) * 1000, 1)
    fps = round(1000.0 / max(elapsed_ms, 1.0), 1)

    annotated_frame = draw_fall_annotation(frame_bgr, person_data_list, fps=fps)
    annotated_b64 = _cv2_to_base64(annotated_frame)

    has_fall = any(p["is_fallen"] for p in person_data_list)
    has_warning = any(p["is_warning"] for p in person_data_list)

    overall_status = "FALL_DETECTED" if has_fall else ("WARNING" if has_warning else "SAFE")

    return {
        "success": True,
        "has_fall": has_fall,
        "overall_status": overall_status,
        "persons_count": len(person_data_list),
        "persons": person_data_list,
        "processing_ms": elapsed_ms,
        "fps": fps,
        "image_width": w,
        "image_height": h,
        "annotated_image": annotated_b64
    }

def process_fall_video(
    video_bytes: bytes,
    angle_threshold: float = 45.0,
    ratio_threshold: float = 1.05,
    sample_interval: int = 2
) -> Dict[str, Any]:
    """
    Processes video clip (e.g. CCTV / MP4 recording):
    - Analyzes frame-by-frame
    - Tracks temporal state of falls
    - Generates output annotated video saved to uploads directory
    - Returns timeline of fall events
    """
    import tempfile
    start_time = time.time()
    detector = get_pose_detector()
    if detector is None:
        raise RuntimeError("MediaPipe Pose detector could not be initialized")

    tmp_in = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f_in:
            f_in.write(video_bytes)
            tmp_in = f_in.name

        cap = cv2.VideoCapture(tmp_in)
        if not cap.isOpened():
            raise ValueError("Tidak dapat membaca format video input")

        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        # Output video file in uploads
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        uploads_dir = os.path.abspath(os.path.join(cur_dir, "..", "..", "uploads"))
        os.makedirs(uploads_dir, exist_ok=True)

        out_filename = f"fall_audit_{uuid.uuid4().hex[:10]}.mp4"
        out_path = os.path.join(uploads_dir, out_filename)

        fourcc = cv2.VideoWriter_fourcc(*"avc1")
        writer = cv2.VideoWriter(out_path, fourcc, fps, (orig_w, orig_h))
        if not writer.isOpened():
            # Fallback to mp4v
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(out_path, fourcc, fps, (orig_w, orig_h))

        timeline_events = []
        fall_frame_count = 0
        total_processed_frames = 0
        max_persons = 0
        peak_fall_snapshot = None

        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            total_processed_frames += 1
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            detection_result = detector.detect(mp_image)

            person_data_list = []
            if detection_result and detection_result.pose_landmarks:
                for landmarks in detection_result.pose_landmarks:
                    analysis = analyze_pose_landmarks(
                        landmarks,
                        img_w=orig_w,
                        img_h=orig_h,
                        angle_threshold=angle_threshold,
                        ratio_threshold=ratio_threshold
                    )
                    person_data_list.append(analysis)

            max_persons = max(max_persons, len(person_data_list))
            frame_has_fall = any(p["is_fallen"] for p in person_data_list)

            timestamp_sec = round(frame_idx / max(fps, 1.0), 2)
            if frame_has_fall:
                fall_frame_count += 1
                timeline_events.append({
                    "frame": frame_idx,
                    "timestamp": timestamp_sec,
                    "status": "FALLEN",
                    "details": [
                        {"angle": p["torso_angle"], "ar": p["aspect_ratio"]}
                        for p in person_data_list if p["is_fallen"]
                    ]
                })

            annotated_frame = draw_fall_annotation(frame, person_data_list, fps=fps)

            # Store snapshot of first major fall
            if frame_has_fall and peak_fall_snapshot is None:
                peak_fall_snapshot = _cv2_to_base64(annotated_frame)

            writer.write(annotated_frame)
            frame_idx += 1

        cap.release()
        writer.release()

        # Fall incident detected if sustained for at least 3 frames
        has_sustained_fall = (fall_frame_count >= 3)
        total_time_ms = round((time.time() - start_time) * 1000, 1)

        return {
            "success": True,
            "has_fall": has_sustained_fall,
            "fall_frame_count": fall_frame_count,
            "total_frames": total_processed_frames,
            "duration_seconds": round(total_processed_frames / max(fps, 1.0), 2),
            "max_persons": max_persons,
            "timeline_events": timeline_events[:50],  # Sample events
            "video_url": f"/api/v1/uploads/{out_filename}",
            "snapshot": peak_fall_snapshot,
            "processing_time_ms": total_time_ms
        }
    finally:
        if tmp_in and os.path.exists(tmp_in):
            try:
                os.remove(tmp_in)
            except Exception:
                pass
