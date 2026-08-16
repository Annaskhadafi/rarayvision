"""
FastAPI Web Application for Mining OTR & Warehouse Tire Object Counter.
Provides real-time MJPEG video streaming, interactive zone management,
multi-source selection (Webcam, Uploaded Video, CCTV RTSP, Simulated Yard),
and live telemetry stats API.
"""

import os
import cv2
import json
import time
import shutil
import threading
from typing import Dict, List, Tuple, Optional, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

from tire_counter import TireCounter

app = FastAPI(title="Mining & Warehouse Tire Object Counter Web UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(SAMPLES_DIR, exist_ok=True)

# Mount static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class StreamManager:
    """
    Manages background video capture and inference loop to serve smooth MJPEG streams.
    """
    def __init__(self):
        self.source_type: str = "sample"  # "sample", "webcam", "upload", "rtsp"
        self.source_path: Any = os.path.join(SAMPLES_DIR, "mining_yard_sample.mp4")
        self.model_name: str = "yolov8n.pt"
        self.conf_thresh: float = 0.25
        self.iou_thresh: float = 0.5
        
        self.yard_zones: Dict[str, List[Tuple[int, int]]] = {
            "Bay-A (New OTR)": [(20, 20), (370, 20), (370, 320), (20, 320)],
            "Bay-B (Scrap / Used)": [(430, 20), (780, 20), (780, 320), (430, 320)],
            "Bay-C (Mounting Bay)": [(20, 360), (370, 360), (370, 580), (20, 580)],
            "Transit Road": [(420, 360), (780, 360), (780, 580), (420, 580)],
        }
        self.transit_line: Optional[List[Tuple[int, int]]] = [(420, 470), (780, 470)]
        
        self.counter: Optional[TireCounter] = None
        self.cap: Optional[cv2.VideoCapture] = None
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_summary: Dict[str, Any] = {
            "total_live_count": 0,
            "zone_counts": {},
            "in_count": 0,
            "out_count": 0,
            "active_tracks": 0,
            "fps": 0.0,
            "status": "idle"
        }
        self.is_running = False
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None

    def start_stream(self, source_type: str, source_path: Any, model_name: str = "yolov8n.pt", conf: float = 0.25):
        with self.lock:
            self.stop_stream_locked()
            self.source_type = source_type
            self.source_path = source_path
            self.model_name = model_name
            self.conf_thresh = conf

            # Make sure sample video exists if selected
            if source_type == "sample":
                if not os.path.exists(self.source_path):
                    from mining_yard_counter import generate_mining_yard_sample_video
                    generate_mining_yard_sample_video(self.source_path)

            print(f"[StreamManager] Initializing TireCounter with {model_name} on {source_path}")
            self.counter = TireCounter(
                model_path=self.model_name,
                conf_threshold=self.conf_thresh,
                iou_threshold=self.iou_thresh,
                zones=self.yard_zones,
                line_points=self.transit_line,
            )

            self.cap = cv2.VideoCapture(self.source_path)
            self.is_running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()

    def stop_stream_locked(self):
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.cap:
            self.cap.release()
            self.cap = None

    def stop_stream(self):
        with self.lock:
            self.stop_stream_locked()

    def update_zones(self, zones: Dict[str, List[Tuple[int, int]]], line: Optional[List[Tuple[int, int]]] = None):
        with self.lock:
            self.yard_zones = zones
            self.transit_line = line
            if self.counter:
                self.counter.zones = zones
                self.counter.line_points = line
                self.counter.current_zone_counts = {k: 0 for k in zones}

    def reset_stats(self):
        with self.lock:
            if self.counter:
                self.counter.in_count = 0
                self.counter.out_count = 0
                self.counter.total_live_count = 0
                self.counter.counted_ids.clear()
                self.counter.event_logs.clear()
                self.counter.track_history.clear()

    def _capture_loop(self):
        fps_time = time.time()
        frame_counter = 0
        fps = 0.0

        while self.is_running and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                # If video file or sample, loop back to start
                if self.source_type in ["sample", "upload"]:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                else:
                    time.sleep(0.1)
                    continue

            frame_counter += 1
            if frame_counter % 10 == 0:
                now = time.time()
                fps = 10.0 / max(0.001, (now - fps_time))
                fps_time = now

            # Process frame through counter
            annotated_frame, summary = self.counter.process_frame(frame, draw_annotated=True)

            summary["fps"] = round(fps, 1)
            summary["status"] = "running"
            summary["source_type"] = self.source_type
            summary["model"] = self.model_name

            with self.lock:
                self.latest_frame = annotated_frame
                self.latest_summary = summary

            # Regulate frame rate slightly on CPU
            time.sleep(0.01)

        print("[StreamManager] Capture loop terminated.")

stream_manager = StreamManager()

# Auto-start default sample stream on startup
@app.on_event("startup")
def startup_event():
    sample_path = os.path.join(SAMPLES_DIR, "mining_yard_sample.mp4")
    if not os.path.exists(sample_path):
        from mining_yard_counter import generate_mining_yard_sample_video
        generate_mining_yard_sample_video(sample_path)
    stream_manager.start_stream("sample", sample_path, model_name="yolov8n.pt", conf=0.25)

@app.get("/")
def index_page():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.post("/api/source/select")
async def select_source(
    source_type: str = Form(...), # "sample", "webcam", "rtsp", "upload"
    camera_index: int = Form(0),
    rtsp_url: str = Form(""),
    model_name: str = Form("yolov8n.pt"),
    conf: float = Form(0.25)
):
    """Switch video source dynamically."""
    if source_type == "webcam":
        src = camera_index
    elif source_type == "rtsp":
        if not rtsp_url.strip():
            raise HTTPException(status_code=400, detail="RTSP URL cannot be empty.")
        src = rtsp_url.strip()
    elif source_type == "sample":
        src = os.path.join(SAMPLES_DIR, "mining_yard_sample.mp4")
    elif source_type == "sample_conveyor":
        src = os.path.join(SAMPLES_DIR, "conveyor_sample.mp4")
        if not os.path.exists(src):
            from generate_sample_video import create_synthetic_tire_video
            create_synthetic_tire_video(src)
    else:
        raise HTTPException(status_code=400, detail="Invalid source type.")

    stream_manager.start_stream(source_type, src, model_name=model_name, conf=conf)
    return {"status": "ok", "source_type": source_type, "source": str(src), "model": model_name}

@app.post("/api/source/upload")
async def upload_video(
    file: UploadFile = File(...),
    model_name: str = Form("yolov8n.pt"),
    conf: float = Form(0.25)
):
    """Upload a custom video file and stream detection."""
    save_path = os.path.join(UPLOADS_DIR, file.filename)
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    stream_manager.start_stream("upload", save_path, model_name=model_name, conf=conf)
    return {"status": "ok", "filename": file.filename, "model": model_name}

@app.get("/api/stream")
def video_feed():
    """Generates MJPEG multipart stream from latest analyzed frame."""
    def generate():
        while True:
            with stream_manager.lock:
                frame = stream_manager.latest_frame
            if frame is None:
                time.sleep(0.05)
                continue

            # Encode as JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ret:
                time.sleep(0.02)
                continue

            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.03)

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/telemetry")
def get_telemetry():
    """Returns current live stock, FPS, zone breakdown, and recent logs."""
    with stream_manager.lock:
        summary = dict(stream_manager.latest_summary)
        logs = list(stream_manager.counter.event_logs[-20:]) if stream_manager.counter else []
    return {
        "summary": summary,
        "recent_events": logs,
        "configured_zones": list(stream_manager.yard_zones.keys()),
    }

@app.post("/api/zones/update")
async def update_zones(payload: Dict[str, Any]):
    """Update custom polygon zones and counting line coordinates."""
    zones = payload.get("zones", {})
    line = payload.get("line", None)
    stream_manager.update_zones(zones, line)
    return {"status": "ok", "zones_count": len(zones), "line_set": bool(line)}

@app.post("/api/reset")
def reset_counts():
    """Reset counters and history."""
    stream_manager.reset_stats()
    return {"status": "ok", "message": "Counters reset successfully."}

@app.get("/api/export/json")
def export_json():
    """Download full inventory audit logs as JSON."""
    with stream_manager.lock:
        if not stream_manager.counter:
            return {"summary": {}, "events": []}
        return {
            "summary": {
                "total_live_yard_count": stream_manager.counter.total_live_count,
                "zone_breakdown": stream_manager.counter.current_zone_counts,
                "total_in": stream_manager.counter.in_count,
                "total_out": stream_manager.counter.out_count,
                "net_delta": stream_manager.counter.in_count - stream_manager.counter.out_count,
            },
            "events": stream_manager.counter.event_logs,
        }

if __name__ == "__main__":
    import uvicorn
    print("Starting Mining Tire Counter Web Server at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
