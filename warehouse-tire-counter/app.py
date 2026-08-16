"""
FastAPI Web Application for Mining OTR & Warehouse Tire Object Counter.
Provides real-time MJPEG video streaming, interactive zone management,
multi-source selection (Webcam, Uploaded Video, CCTV RTSP, Simulated Yard),
and live telemetry stats API.
"""

import os
import sys
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import cv2
import json
import time
import shutil
import threading
import subprocess

from typing import Dict, List, Tuple, Optional, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

import tempfile

# ── yt-dlp URL Resolver ────────────────────────────────────────────────────
_YTDLP_DOMAINS = (
    "youtube.com", "youtu.be",
    "twitch.tv",
    "facebook.com", "fb.watch",
    "instagram.com",
    "tiktok.com",
    "bilibili.com",
    "dailymotion.com",
    "vimeo.com",
)

def _extract_with_ytdlp(url: str) -> str:
    """
    Use yt-dlp Python API to resolve video/stream URLs:
    - If Live Stream: returns direct HLS / m3u8 stream URL.
    - If VOD / Video: downloads to local temp cache and returns file path for smooth continuous playback.
    """
    try:
        import yt_dlp
    except ImportError:
        try:
            import subprocess
            subprocess.run(["pip", "install", "yt-dlp", "-q"], check=True, timeout=30)
            import yt_dlp
        except Exception as e:
            print(f"[TireCounter] yt-dlp install failed: {e}")
            return url

    try:
        print(f"[TireCounter] Resolving media URL via yt-dlp: {url}")
        ydl_opts_info = {
            'format': 'best[ext=mp4]/best',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web']
                }
            },
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            is_live = info.get('is_live', False) or info.get('was_live', False)
            video_id = info.get('id', 'stream')
            direct_url = info.get('url', '')

            # If it's a live HLS stream (.m3u8), return stream URL directly
            if is_live and direct_url:
                print(f"[TireCounter] Detected Live Stream: {direct_url[:80]}...")
                return direct_url

            # If it's a video file / VOD, download to local cache for 100% reliable frame decoding
            cache_dir = os.path.join(tempfile.gettempdir(), "raray_media_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cached_path = os.path.join(cache_dir, f"media_{video_id}.mp4")

            if os.path.exists(cached_path) and os.path.getsize(cached_path) > 1000:
                print(f"[TireCounter] Using existing cached media: {cached_path}")
                return cached_path

            print(f"[TireCounter] Downloading video to cache: {cached_path}")
            ydl_opts_download = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': cached_path,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web']
                    }
                },
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl_dl:
                ydl_dl.download([url])

            if os.path.exists(cached_path):
                print(f"[TireCounter] Video cached successfully ({os.path.getsize(cached_path)} bytes)")
                return cached_path

            if direct_url:
                return direct_url

    except Exception as e:
        print(f"[TireCounter] yt-dlp resolution error: {e}")
        raise ValueError(f"Could not extract stream from URL: {e}")

    return url


def resolve_stream_url(url: str) -> str:
    """Auto-detect social platform URLs and extract real stream via yt-dlp."""
    if not isinstance(url, str):
        return url
    lowered = url.lower()
    if any(d in lowered for d in _YTDLP_DOMAINS):
        return _extract_with_ytdlp(url)
    return url
# ──────────────────────────────────────────────────────────────────────────


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

    def start_stream(self, source_type: str, source_path: Any, model_name: str = "yolov8n.pt", conf: float = 0.25, iou: float = 0.45):
        with self.lock:
            self.stop_stream_locked()
            self.latest_frame = None
            self.source_type = source_type
            self.source_path = source_path
            self.model_name = model_name
            self.conf_thresh = conf
            self.iou_thresh = iou

            # Make sure sample video exists if selected
            if source_type == "sample":
                if not os.path.exists(self.source_path):
                    from mining_yard_counter import generate_mining_yard_sample_video
                    generate_mining_yard_sample_video(self.source_path)

            print(f"[StreamManager] Initializing TireCounter with {model_name} on {source_path}")
            # Use predefined zones only for built-in sample yard simulation
            use_zones = self.yard_zones if source_type == "sample" else {}
            use_line = self.transit_line if source_type == "sample" else None

            self.counter = TireCounter(
                model_path=self.model_name,
                conf_threshold=self.conf_thresh,
                iou_threshold=self.iou_thresh,
                zones=use_zones,
                line_points=use_line,
            )

            # Open video capture with appropriate backend flags
            is_network_stream = (
                source_type in ("rtsp", "public_url")
                and isinstance(source_path, str)
                and source_path.startswith(("rtsp://", "rtmp://", "http://", "https://", "udp://", "tcp://"))
            )

            if is_network_stream:
                # Use FFMPEG backend for maximum format compatibility (m3u8, HLS, MJPEG, RTSP, RTMP)
                self.cap = cv2.VideoCapture(self.source_path, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
            else:
                self.cap = cv2.VideoCapture(self.source_path)
                if not self.cap.isOpened() and isinstance(self.source_path, str):
                    self.cap = cv2.VideoCapture(self.source_path, cv2.CAP_FFMPEG)

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
        reconnect_attempts = 0
        max_reconnect = 5  # For network streams, try to reconnect on failure

        is_network = isinstance(self.source_path, str) and self.source_path.startswith(
            ("rtsp://", "rtmp://", "http://", "https://", "udp://", "tcp://")
        )
        is_file = (not is_network) or self.source_type in ("sample", "sample_conveyor", "upload", "public_url")

        while self.is_running:
            if not self.cap or not self.cap.isOpened():
                if is_network and reconnect_attempts < max_reconnect:
                    reconnect_attempts += 1
                    print(f"[StreamManager] Network stream disconnected. Reconnecting ({reconnect_attempts}/{max_reconnect})...")
                    time.sleep(2)
                    self.cap = cv2.VideoCapture(self.source_path, cv2.CAP_FFMPEG)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
                    continue
                elif is_file and reconnect_attempts < max_reconnect:
                    reconnect_attempts += 1
                    print(f"[StreamManager] Opening file source ({reconnect_attempts}/{max_reconnect})...")
                    time.sleep(1)
                    self.cap = cv2.VideoCapture(self.source_path)
                    if not self.cap.isOpened():
                        self.cap = cv2.VideoCapture(self.source_path, cv2.CAP_FFMPEG)
                    continue
                else:
                    print("[StreamManager] Source unavailable or max reconnects reached. Setting error frame.")
                    err_frame = np.zeros((480, 854, 3), dtype=np.uint8)
                    cv2.putText(err_frame, "VIDEO SOURCE UNAVAILABLE / DISCONNECTED", (70, 230),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 70, 255), 2)
                    cv2.putText(err_frame, "Please check the stream URL and reconnect below.", (120, 270),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
                    with self.lock:
                        self.latest_frame = err_frame
                        self.latest_summary["status"] = "error"
                    break


            ret, frame = self.cap.read()
            if not ret:
                if is_file:
                    # Loop file-based sources
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                elif is_network and reconnect_attempts < max_reconnect:
                    reconnect_attempts += 1
                    print(f"[StreamManager] Frame read failed. Reconnecting ({reconnect_attempts}/{max_reconnect})...")
                    time.sleep(1)
                    self.cap.release()
                    self.cap = cv2.VideoCapture(self.source_path, cv2.CAP_FFMPEG)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
                    continue
                else:
                    time.sleep(0.05)
                    continue

            # Successful read — reset reconnect counter
            reconnect_attempts = 0

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
            summary["source_url"] = str(self.source_path) if isinstance(self.source_path, str) else f"webcam:{self.source_path}"
            summary["model"] = self.model_name

            with self.lock:
                self.latest_frame = annotated_frame
                self.latest_summary = summary

            # Regulate frame rate slightly on CPU
            time.sleep(0.01)

        print("[StreamManager] Capture loop terminated.")

    @property
    def running(self) -> bool:
        return self.is_running



stream_manager = StreamManager()

def ensure_default_stream():
    """Lazily start the default mining yard stream if no stream is currently active."""
    try:
        if not getattr(stream_manager, "is_running", False):
            sample_path = os.path.join(SAMPLES_DIR, "mining_yard_sample.mp4")
            if not os.path.exists(sample_path):
                try:
                    from mining_yard_counter import generate_mining_yard_sample_video
                    generate_mining_yard_sample_video(sample_path)
                except Exception as ex:
                    print(f"[TireCounter] Sample generator warning: {ex}")
            if os.path.exists(sample_path):
                stream_manager.start_stream("sample", sample_path, model_name="yolov8n.pt", conf=0.25)
    except Exception as e:
        print(f"[TireCounter] ensure_default_stream error: {e}")

# Trigger auto-start in background
try:
    threading.Thread(target=ensure_default_stream, daemon=True).start()
except Exception as e:
    print(f"[TireCounter] Background thread launch error: {e}")

# Auto-start default sample stream on startup in background
@app.on_event("startup")
def startup_event():
    try:
        ensure_default_stream()
    except Exception as e:
        print(f"[TireCounter] startup_event error: {e}")


@app.get("/")
def index_page():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))



@app.post("/api/source/select")
async def select_source(
    source_type: str = Form(...), # "sample", "webcam", "rtsp", "upload", "public_url"
    camera_index: int = Form(0),
    rtsp_url: str = Form(""),
    public_url: str = Form(""),
    model_name: str = Form("yolov8n.pt"),
    conf: float = Form(0.25),
    iou: float = Form(0.45),
):
    """
    Switch video source dynamically.
    Supported source_type values:
      - 'sample'         : Built-in simulated mining yard video
      - 'sample_conveyor': Built-in conveyor belt simulation
      - 'webcam'         : Local USB / integrated webcam by index
      - 'rtsp'           : RTSP stream (rtsp://...)
      - 'public_url'     : Any public stream URL:
                           rtsp://, rtmp://, http://, https://
                           including m3u8 HLS, MJPEG IP cam, city cameras, etc.
      - 'upload'         : Previously uploaded video file
    """
    st = source_type.lower().strip()
    if st in ("webcam", "camera"):
        src = camera_index
    elif st in ("rtsp", "cctv"):
        url = (rtsp_url or public_url).strip()
        if not url:
            raise HTTPException(status_code=400, detail="RTSP URL cannot be empty.")
        src = url
    elif st in ("public_url", "public", "url", "stream", "city_cam", "youtube"):
        url = (public_url or rtsp_url).strip()
        if not url:
            raise HTTPException(status_code=400, detail="Public URL cannot be empty.")
        # Auto-fix missing protocol (e.g. youtube.com or www.youtube.com)
        if not any(url.lower().startswith(s) for s in ("http://", "https://", "rtsp://", "rtmp://", "udp://", "tcp://")):
            url = "https://" + url
        try:
            src = resolve_stream_url(url)
        except Exception as ex:
            raise HTTPException(status_code=400, detail=f"Failed to load stream: {ex}")
    elif st in ("sample", "mining_yard"):
        src = os.path.join(SAMPLES_DIR, "mining_yard_sample.mp4")
    elif st in ("sample_conveyor", "conveyor"):
        src = os.path.join(SAMPLES_DIR, "conveyor_sample.mp4")
        if not os.path.exists(src):
            from generate_sample_video import create_synthetic_tire_video
            create_synthetic_tire_video(src)
    elif st == "upload":
        src = (public_url or rtsp_url).strip()
    else:
        # Fallback: if it starts with http/rtsp, treat as public_url
        if any(source_type.lower().startswith(s) for s in ("http://", "https://", "rtsp://", "rtmp://")):
            src = resolve_stream_url(source_type.strip())
            st = "public_url"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid source type: '{source_type}'.")

    stream_manager.start_stream(st, src, model_name=model_name, conf=conf, iou=iou)
    return {"status": "ok", "source_type": st, "source": str(src), "model": model_name}


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
    ensure_default_stream()

    def generate():
        standby_rendered = False
        while True:
            with stream_manager.lock:
                frame = stream_manager.latest_frame

            if frame is None:
                # Render a standby frame so the browser doesn't wait with a blank black screen
                standby = np.zeros((480, 854, 3), dtype=np.uint8)
                cv2.putText(standby, "MINING OTR & WAREHOUSE TIRE COUNTER", (80, 210),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
                cv2.putText(standby, "Initializing YOLO Model & Video Pipeline...", (140, 260),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 215, 255), 1)
                cv2.putText(standby, "Select source or model below to stream live detection", (120, 300),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
                _, buffer = cv2.imencode('.jpg', standby, [cv2.IMWRITE_JPEG_QUALITY, 80])
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                time.sleep(0.5)
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
    ensure_default_stream()
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
    print("Starting Mining Tire Counter Web Server at http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
