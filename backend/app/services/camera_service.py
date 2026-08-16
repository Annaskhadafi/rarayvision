import cv2
import time
import json
import numpy as np
import base64
from typing import Generator

from backend.app.services.hse_service import (
    process_ppe_check,
    process_danger_zone_alert,
    process_near_miss_log
)
from backend.app.services.inventory_service import (
    process_count_boxes,
    process_defect_check,
    process_shelf_occupancy
)

import os
import urllib.parse

import subprocess
import shutil

import tempfile

# Domains that require yt-dlp to extract real stream URLs
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
            print(f"[CameraService] yt-dlp install failed: {e}")
            return url

    try:
        print(f"[CameraService] Resolving media URL via yt-dlp: {url}")
        ydl_opts_info = {
            'format': 'best[ext=mp4]/best',
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
                print(f"[CameraService] Detected Live Stream: {direct_url[:80]}...")
                return direct_url

            # If it's a video file / VOD, download to local cache for 100% reliable frame decoding
            cache_dir = os.path.join(tempfile.gettempdir(), "raray_media_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cached_path = os.path.join(cache_dir, f"media_{video_id}.mp4")

            if os.path.exists(cached_path) and os.path.getsize(cached_path) > 1000:
                print(f"[CameraService] Using existing cached media: {cached_path}")
                return cached_path

            print(f"[CameraService] Downloading video to cache: {cached_path}")
            ydl_opts_download = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': cached_path,
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl_dl:
                ydl_dl.download([url])

            if os.path.exists(cached_path):
                print(f"[CameraService] Video cached successfully ({os.path.getsize(cached_path)} bytes)")
                return cached_path

            if direct_url:
                return direct_url

    except Exception as e:
        print(f"[CameraService] yt-dlp resolution error: {e}")

    return url


def _resolve_stream_source(stream_url: str):
    """Converts numeric string e.g. '0' to integer for local webcam or keeps RTSP/HTTP string.
    Automatically extracts real stream URLs or cached video files from YouTube/social platforms."""
    s_url = stream_url.strip()
    if s_url.isdigit():
        return int(s_url)

    # Detect social media platform URLs and resolve via yt-dlp
    lowered = s_url.lower()
    if any(domain in lowered for domain in _YTDLP_DOMAINS):
        s_url = _extract_with_ytdlp(s_url)

    # Auto-fix unencoded '#' or special characters in RTSP password
    if isinstance(s_url, str) and s_url.lower().startswith("rtsp://") and "@" in s_url:
        try:
            proto_prefix, rest = s_url.split("://", 1)
            userpass, hostpath = rest.rsplit("@", 1)
            if ":" in userpass:
                user, password = userpass.split(":", 1)
                if "#" in password and "%23" not in password:
                    safe_pass = urllib.parse.quote(password, safe="")
                    s_url = f"{proto_prefix}://{user}:{safe_pass}@{hostpath}"
        except Exception as e:
            print(f"[CameraService] URL auto-fix warning: {e}")

    return s_url


import concurrent.futures

try:
    import av
    HAS_PYAV = True
except ImportError:
    HAS_PYAV = False

def _read_frame_pyav(url: str):
    """Fallback decoder for H.265 / HEVC streams using PyAV."""
    if not HAS_PYAV:
        return False, None
    try:
        container = av.open(url, options={'rtsp_transport': 'tcp', 'stimeout': '3000000'})
        video_stream = container.streams.video[0]
        for packet in container.demux(video_stream):
            for frame in packet.decode():
                img = frame.to_ndarray(format='bgr24')
                container.close()
                return True, img
        container.close()
    except Exception as e:
        print(f"[CameraService] PyAV H.265 decode info: {e}")
    return False, None

def _do_test_connection(source):
    if isinstance(source, str) and source.lower().startswith("rtsp"):
        # Force TCP transport and 3-second socket timeout in FFmpeg
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;3000000|rw_timeout;3000000"

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        return {
            "online": False,
            "message": "Gagal menghubungkan ke kamera. Pastikan IP/RTSP, Username, Password, dan Port 554 benar serta kamera terhubung."
        }

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        if isinstance(source, str) and HAS_PYAV:
            ret_pyav, frame_pyav = _read_frame_pyav(source)
            if ret_pyav and frame_pyav is not None:
                h, w, _ = frame_pyav.shape
                return {
                    "online": True,
                    "resolution": f"{w}x{h}",
                    "message": f"Kamera ONLINE! (Format H.265 / HEVC Decoded). Resolusi: {w}x{h} px"
                }

        return {
            "online": False,
            "message": "Kamera terhubung tetapi tidak mengirimkan data frame. Masalah umum Hikvision: Ubah Stream Format di Hikvision Web dari H.265 / H.265+ menjadi H.264."
        }

    h, w, _ = frame.shape
    return {
        "online": True,
        "resolution": f"{w}x{h}",
        "message": f"Kamera ONLINE! Resolusi: {w}x{h} px"
    }

def test_camera_connection(stream_url: str) -> dict:
    """
    Tests OpenCV VideoCapture connection to RTSP/HTTP stream URL with a strict 4.0s timeout
    to prevent Nginx 504 Gateway Timeout on unreachable camera IPs.
    """
    source = _resolve_stream_source(stream_url)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_test_connection, source)
        try:
            return future.result(timeout=4.0)
        except concurrent.futures.TimeoutError:
            return {
                "online": False,
                "message": f"Koneksi Timeout (4s). IP Kamera tidak dapat dijangkau dari server cloud. Jika ini IP lokal LAN (192.168.x.x), pastikan server berada di jaringan LAN yang sama atau gunakan Port Forwarding / DDNS / VPN."
            }
        except Exception as e:
            return {
                "online": False,
                "message": f"Gagal menguji koneksi kamera: {str(e)}"
            }

def generate_mjpeg_feed(
    stream_url: str,
    enable_ai_overlay: bool = True,
    ai_module: str = "hse",
    db_session = None
) -> Generator[bytes, None, None]:
    """
    Generator yielding multipart MJPEG frames for live browser video feed with real-time AI overlays.
    Supports all HSE and Inventory AI modules.
    """
    source = _resolve_stream_source(stream_url)
    is_network = isinstance(source, str) and any(
        source.lower().startswith(p) for p in ("rtsp://", "rtmp://", "http://", "https://")
    )
    if is_network and source.lower().startswith("rtsp"):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;3000000|rw_timeout;3000000"
    if is_network:
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
    else:
        cap = cv2.VideoCapture(source)

    frame_skip = 2  # Process AI every 2nd frame for smooth 25 FPS feed
    frame_counter = 0
    last_annotated_frame = None

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            # If it is a video file (e.g. cached YouTube video or mp4), loop from beginning
            if isinstance(source, str) and not is_network and os.path.exists(source):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()

            # Try PyAV fallback for H.265 / HEVC stream
            if (not ret or frame is None) and isinstance(source, str) and HAS_PYAV:
                ret_pyav, frame_pyav = _read_frame_pyav(source)
                if ret_pyav and frame_pyav is not None:
                    ret = True
                    frame = frame_pyav


        if not ret or frame is None:
            offline_img = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(offline_img, "CCTV STREAM OFFLINE / UNREACHABLE", (40, 220),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.putText(offline_img, f"IP: {stream_url}", (40, 260),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
            cv2.putText(offline_img, "Gunakan IP Publik/DDNS/VPN jika diakses dari Cloud", (40, 290),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
            
            _, buffer = cv2.imencode(".jpg", offline_img)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(2.0)
            cap.release()
            cap = cv2.VideoCapture(source)
            continue

        frame_counter += 1

        if enable_ai_overlay and (frame_counter % frame_skip == 0 or last_annotated_frame is None):
            try:
                _, img_encoded = cv2.imencode(".jpg", frame)
                img_bytes = img_encoded.tobytes()

                res = None
                mod = ai_module.lower()

                if mod in ["hse", "hse_danger_zone"]:
                    res = process_danger_zone_alert(img_bytes, [], confidence=0.4)
                elif mod == "hse_ppe":
                    res = process_ppe_check(img_bytes, {"require_helmet": True, "require_vest": True}, confidence=0.4)
                elif mod == "hse_near_miss":
                    res = process_near_miss_log(img_bytes, [], {"require_helmet": True, "require_vest": True}, confidence=0.4)
                elif mod in ["inventory", "inventory_count"]:
                    res = process_count_boxes(img_bytes, confidence=0.4)
                elif mod == "inventory_defect":
                    res = process_defect_check(img_bytes, confidence=0.4)
                elif mod == "inventory_shelf":
                    res = process_shelf_occupancy(img_bytes, 3, 4, confidence=0.4)
                else:
                    res = process_danger_zone_alert(img_bytes, [], confidence=0.4)

                if res and "annotated_image" in res:
                    b64_data = res["annotated_image"]
                    if b64_data and "," in b64_data:
                        raw_bytes = base64.b64decode(b64_data.split(",")[1])
                        nparr = np.frombuffer(raw_bytes, np.uint8)
                        decoded = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if decoded is not None:
                            last_annotated_frame = decoded
                        else:
                            last_annotated_frame = frame
                    else:
                        last_annotated_frame = frame
                else:
                    last_annotated_frame = frame
            except Exception as e:
                print(f"[CameraService] AI overlay error ({ai_module}): {e}")
                last_annotated_frame = frame

        display_frame = last_annotated_frame if (enable_ai_overlay and last_annotated_frame is not None) else frame

        _, buffer = cv2.imencode(".jpg", display_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

        time.sleep(0.04)
