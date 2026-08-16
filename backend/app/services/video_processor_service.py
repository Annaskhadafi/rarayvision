import os
import uuid
import time
import tempfile
import cv2
import numpy as np

from backend.app.services.hse_service import (
    process_ppe_check,
    process_danger_zone_alert,
    process_near_miss_log,
    _cv2_to_base64
)
from backend.app.services.inventory_service import (
    process_count_boxes,
    process_defect_check,
    process_shelf_occupancy
)

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
if not os.path.exists(UPLOADS_DIR):
    os.makedirs(UPLOADS_DIR)

def process_video_file(
    video_bytes: bytes,
    module: str = "hse",
    action: str = "ppe_check",
    options: dict = None
) -> dict:
    """
    Processes a full video file frame-by-frame, applying AI object detection & Supervision tracking.
    Outputs an annotated MP4 video file saved in uploads and returns its web-accessible URL.
    """
    start_time = time.time()
    options = options or {}
    confidence = options.get("confidence", 0.4)

    # Write video bytes to temp file
    temp_input = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    with open(temp_input, "wb") as f:
        f.write(video_bytes)

    cap = cv2.VideoCapture(temp_input)
    if not cap.isOpened():
        if os.path.exists(temp_input):
            os.remove(temp_input)
        raise ValueError("Gagal membuka file video. Format tidak didukung.")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    # Generate unique output filename
    out_filename = f"annotated_video_{uuid.uuid4().hex[:10]}.mp4"
    output_path = os.path.join(UPLOADS_DIR, out_filename)

    # Use mp4v codec for cross-platform compatibility
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out_writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    first_annotated_b64 = None
    processed_frames = 0
    max_frames = 600  # Cap at 600 frames (~24s) to prevent server timeout on long videos

    last_summary = {}

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or frame is None or processed_frames >= max_frames:
            break

        processed_frames += 1

        # Encode frame to JPEG bytes for AI service pipelines
        _, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        frame_bytes = buffer.tobytes()

        # Run AI module detection
        res = None
        try:
            if module == "hse":
                if action == "danger_zone":
                    res = process_danger_zone_alert(frame_bytes, options.get("danger_zones", []), confidence)
                elif action == "near_miss":
                    res = process_near_miss_log(frame_bytes, options.get("danger_zones", []), confidence)
                else: # ppe_check
                    res = process_ppe_check(frame_bytes, options.get("ppe_rules", {}), confidence)
            else: # inventory
                if action == "defect_check":
                    res = process_defect_check(frame_bytes, confidence)
                elif action == "shelf_occupancy":
                    res = process_shelf_occupancy(frame_bytes, options.get("grid_rows", 3), options.get("grid_cols", 4), confidence)
                else: # count_boxes
                    res = process_count_boxes(frame_bytes, confidence)
        except Exception as e:
            print(f"[VideoProcessor] Frame {processed_frames} AI error: {e}")

        # Extract annotated frame from base64 response if available
        annotated_frame = frame
        if res and "annotated_image" in res:
            b64 = res["annotated_image"]
            if b64 and "," in b64:
                import base64
                raw_bytes = base64.b64decode(b64.split(",")[1])
                nparr = np.frombuffer(raw_bytes, np.uint8)
                decoded = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if decoded is not None:
                    annotated_frame = decoded

            last_summary = res

        # Capture first frame as thumbnail preview
        if first_annotated_b64 is None:
            first_annotated_b64 = _cv2_to_base64(annotated_frame)

        # Write frame to video stream
        out_writer.write(annotated_frame)

    cap.release()
    out_writer.release()

    if os.path.exists(temp_input):
        try:
            os.remove(temp_input)
        except Exception:
            pass

    # Transcode to web-friendly H.264 (yuv420p) via FFmpeg if available
    web_filename = f"web_{out_filename}"
    web_output_path = os.path.join(UPLOADS_DIR, web_filename)
    try:
        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-i", output_path,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            web_output_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0 and os.path.exists(web_output_path) and os.path.getsize(web_output_path) > 0:
            os.remove(output_path)
            out_filename = web_filename
    except Exception as e:
        print(f"[VideoProcessor] FFmpeg H.264 transcode warning: {e}")

    proc_time = int((time.time() - start_time) * 1000)

    # Return web relative URL for frontend video player
    video_url = f"/api/v1/uploads/{out_filename}"

    # Merge last summary data with video result metadata
    result = {
        "success": True,
        "is_video": True,
        "video_url": video_url,
        "annotated_image": first_annotated_b64,
        "total_frames_processed": processed_frames,
        "total_frames_file": total_frames,
        "fps": fps,
        "duration_sec": round(processed_frames / fps, 1) if fps > 0 else 0,
        "processing_ms": proc_time
    }
    
    # Merge summary metrics
    for k, v in last_summary.items():
        if k not in result:
            result[k] = v

    return result
