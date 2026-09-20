import os
import io
import uuid
import json
import zipfile
import shutil
import asyncio
import threading
import tempfile
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote, unquote, urlparse
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status, BackgroundTasks, Header
from fastapi.responses import JSONResponse, Response, FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pydantic import Field, root_validator

try:
    from backend.app.database.database import get_db
    from backend.app.database.models import MLModel, MLPrediction, MLEndpoint, MLDataset
    from backend.app.core.deps import get_current_user
    from backend.app.database.models import User
    from backend.app.database.database import SessionLocal
    from backend.app.services.detection_service import detection_service
    from backend.app.services.s3_service import s3_service, get_storage_proxy_url, get_presigned_download_url, get_s3_credentials
    from backend.app.services.label_studio_service import label_studio_service
    from backend.app.core.config import BASE_DIR
except ImportError:
    from app.database.database import get_db
    from app.database.models import MLModel, MLPrediction, MLEndpoint, MLDataset
    from app.core.deps import get_current_user
    from app.database.models import User
    from app.database.database import SessionLocal
    from app.services.detection_service import detection_service
    from app.services.s3_service import s3_service, get_storage_proxy_url, get_presigned_download_url, get_s3_credentials
    from app.services.label_studio_service import label_studio_service
    from app.core.config import BASE_DIR

router = APIRouter(prefix="/api/v1/models", tags=["Object Detection & MLOps"])

_dataset_jobs: Dict[str, Dict[str, Any]] = {}
_dataset_jobs_lock = threading.Lock()
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "https://vision.chitraparatama.com").rstrip("/")


def _stable_dataset_url(value: str) -> str:
    """Convert this app's storage URLs to absolute, stable proxy URLs."""
    if not isinstance(value, str) or not value:
        return value
    if value.startswith("/api/v1/uploads/"):
        return f"{PUBLIC_APP_URL}{value}"
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return value
    proxy_path = get_storage_proxy_url(value)
    if proxy_path:
        return f"{PUBLIC_APP_URL}{proxy_path}"
    if parsed.netloc == urlparse(PUBLIC_APP_URL).netloc and parsed.path.startswith("/api/v1/uploads/"):
        return f"{PUBLIC_APP_URL}{parsed.path}"
    return value


def _dataset_import_url(dataset_id: str) -> str:
    return f"{PUBLIC_APP_URL}/api/v1/models/data/datasets/{dataset_id}/label-studio-tasks.json"


def _dataset_image_url(
    value: str,
    folder: str,
    image_urls: Optional[Dict[str, str]] = None,
    original_filename: Optional[str] = None,
) -> str:
    filename = (original_filename or value).replace("\\", "/").rsplit("/", 1)[-1]
    if image_urls:
        for candidate in (filename, unquote(filename)):
            if candidate in image_urls:
                mapped_url = image_urls[candidate]
                if mapped_url.startswith("/api/v1/uploads/"):
                    directory = mapped_url.rsplit("/", 1)[0]
                    return f"{PUBLIC_APP_URL}{directory}/{quote(candidate, safe='')}"
                parsed_mapped = urlparse(mapped_url)
                if (
                    parsed_mapped.netloc == urlparse(PUBLIC_APP_URL).netloc
                    and parsed_mapped.path.startswith("/api/v1/uploads/")
                ):
                    directory = parsed_mapped.path.rsplit("/", 1)[0]
                    return f"{PUBLIC_APP_URL}{directory}/{quote(candidate, safe='')}"
                return _stable_dataset_url(mapped_url)
    stable_url = _stable_dataset_url(value)
    if not value or stable_url != value or urlparse(value).scheme in ("http", "https"):
        return stable_url
    if not filename:
        return value
    _, _, prefix, _, access_key, secret_key = get_s3_credentials()
    storage_root = prefix if access_key and secret_key else "s3_storage"
    key = "/".join(part.strip("/") for part in (storage_root, "datasets", folder, "images", filename) if part)
    return f"{PUBLIC_APP_URL}/api/v1/uploads/{quote(key, safe='/')}"


def build_colab_snippets(folder_name: str, yolo_yaml_url: str, tasks_url: str, coco_url: str) -> Dict[str, str]:
    app_base_url = PUBLIC_APP_URL
    dataset_setup_script = f"""import os, glob, shutil, time, requests, yaml
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm

APP_URL = "{app_base_url}"

# 1. Setup persistent session with retries & connection pooling
session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
    raise_on_status=False
)
adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
session.mount('https://', adapter)
session.mount('http://', adapter)

# 2. Setup dataset dirs
base_dir = os.path.abspath('dataset')
train_img = os.path.join(base_dir, 'images', 'train')
val_img = os.path.join(base_dir, 'images', 'val')
train_lbl = os.path.join(base_dir, 'labels', 'train')
val_lbl = os.path.join(base_dir, 'labels', 'val')
for p in [train_img, val_img, train_lbl, val_lbl]:
    os.makedirs(p, exist_ok=True)

# 3. Download data.yaml & tasks
try:
    r_yaml = session.get('{yolo_yaml_url}', timeout=(10, 60))
    if r_yaml.status_code == 200:
        with open('data.yaml', 'wb') as f:
            f.write(r_yaml.content)
except Exception as e:
    print(f'Warning downloading data.yaml: {{e}}')

with open('data.yaml', 'r') as f:
    cfg = yaml.safe_load(f) or {{}}
raw_names = cfg.get('names', {{0: 'object'}})
if isinstance(raw_names, dict):
    name_to_id = {{str(v).lower(): int(k) for k, v in raw_names.items()}}
elif isinstance(raw_names, list):
    name_to_id = {{str(v).lower(): i for i, v in enumerate(raw_names)}}
else:
    name_to_id = {{'object': 0}}

tasks = []
try:
    r_tasks = session.get('{tasks_url}', timeout=(15, 90))
    if r_tasks.status_code == 200:
        tasks = r_tasks.json()
except Exception as e:
    print(f'Warning downloading tasks: {{e}}')

print(f'Loaded {{len(tasks)}} tasks from S3')

def dl_item(idx_item):
    idx, item = idx_item
    img_url = item.get('data', {{}}).get('image', '')
    if not img_url:
        return
    # Convert private S3 URL to authenticated app proxy URL
    if 'is3.cloudhost.id/onechitra/' in img_url:
        img_url = img_url.replace('https://is3.cloudhost.id/onechitra/', f'{{APP_URL}}/api/v1/uploads/').replace('http://is3.cloudhost.id/onechitra/', f'{{APP_URL}}/api/v1/uploads/')
    elif img_url.startswith('/api/v1/uploads/'):
        img_url = f'{{APP_URL}}{{img_url}}'

    fname = item.get('data', {{}}).get('original_filename') or os.path.basename(img_url.split('?')[0]) or f'img_{{idx}}.jpg'
    if not fname.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp')):
        fname = f'img_{{idx}}.jpg'
    split = 'val' if (len(tasks) > 1 and idx % 5 == 0) else 'train'
    dest_img = os.path.join(base_dir, 'images', split, fname)
    dest_lbl = os.path.join(base_dir, 'labels', split, os.path.splitext(fname)[0] + '.txt')

    for attempt in range(3):
        try:
            res = session.get(img_url, timeout=(15, 60), stream=True)
            if res.status_code == 403 and ('is3.cloudhost.id' in img_url or 'onechitra' in img_url):
                suffix = img_url.split('/onechitra/')[-1] if '/onechitra/' in img_url else img_url.split('.id/')[-1]
                fallback_url = f"{{APP_URL}}/api/v1/uploads/{{suffix.lstrip('/')}}"
                res = session.get(fallback_url, timeout=(15, 60), stream=True)

            if res.status_code == 200:
                with open(dest_img, 'wb') as f:
                    for chunk in res.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                lines = []
                for ann in item.get('annotations', [{{}}])[0].get('result', []):
                    v = ann.get('value', {{}})
                    lbls = v.get('rectanglelabels', ['object'])
                    first_lbl = str(lbls[0]).lower() if lbls else 'object'
                    cid = name_to_id.get(first_lbl, 0)
                    xc = (v.get('x', 0) + v.get('width', 0) / 2.0) / 100.0
                    yc = (v.get('y', 0) + v.get('height', 0) / 2.0) / 100.0
                    lines.append(f"{{cid}} {{xc:.6f}} {{yc:.6f}} {{v.get('width',0)/100.0:.6f}} {{v.get('height',0)/100.0:.6f}}")
                with open(dest_lbl, 'w') as lf:
                    lf.write('\\n'.join(lines))
                return
            elif res.status_code == 404:
                return
        except Exception:
            if attempt < 2:
                time.sleep(1 + attempt)

with ThreadPoolExecutor(max_workers=6) as ex:
    list(tqdm(ex.map(dl_item, enumerate(tasks)), total=len(tasks)))

# Fallback ensure both train and val have files
t_imgs = glob.glob(os.path.join(train_img, '*.*'))
v_imgs = glob.glob(os.path.join(val_img, '*.*'))
if not v_imgs and t_imgs:
    for f in t_imgs[:max(1, len(t_imgs)//5)]:
        shutil.copy(f, val_img)
        lbl = os.path.join(train_lbl, os.path.splitext(os.path.basename(f))[0] + '.txt')
        if os.path.exists(lbl): shutil.copy(lbl, val_lbl)
elif not t_imgs and v_imgs:
    for f in v_imgs:
        shutil.copy(f, train_img)
        lbl = os.path.join(val_lbl, os.path.splitext(os.path.basename(f))[0] + '.txt')
        if os.path.exists(lbl): shutil.copy(lbl, train_lbl)

cfg['path'] = base_dir
cfg['train'] = 'images/train'
cfg['val'] = 'images/val'
with open('data.yaml', 'w') as f:
    yaml.dump(cfg, f, sort_keys=False)

train_cnt = len(glob.glob(os.path.join(train_img, '*.*')))
val_cnt = len(glob.glob(os.path.join(val_img, '*.*')))
print(f'✓ Dataset Ready! Train: {{train_cnt}} | Val: {{val_cnt}}')
if train_cnt == 0:
    raise RuntimeError(f'Gagal mengunduh dataset: Tidak ada gambar di folder train (0 images). Pastikan server {{APP_URL}} dapat diakses.')
"""

    yolo_code = f"""# ==========================================
# 🚀 GOOGLE COLAB TRAINING PIPELINE (YOLO-X / YOLO11-X: 200 EPOCHS, T4 GPU)
# Dataset: {folder_name} (Auto-Resume Supported)
# ==========================================
!pip install -q ultralytics pyyaml requests tqdm

# 1. Download & Prepare Dataset Locally
{dataset_setup_script}

# 2. Train YOLO-X (200 Epochs, T4 GPU dengan Auto-Resume jika Terputus)
from ultralytics import YOLO
import os

last_ckpt = "raray_vision_runs/yolo_x_200epochs/weights/last.pt"
if os.path.exists(last_ckpt):
    print(f"🔄 Checkpoint ditemukan: {{last_ckpt}}! Melanjutkan training (Auto-Resume)...")
    model = YOLO(last_ckpt)
    results = model.train(resume=True)
else:
    print("🚀 Memulai training baru YOLO-X (200 Epochs)...")
    model = YOLO("yolo11x.pt")
    results = model.train(
        data="data.yaml",
        epochs=200,
        imgsz=640,
        device=0,
        batch=16,
        optimizer="AdamW",
        save_period=5,
        project="raray_vision_runs",
        name="yolo_x_200epochs"
    )

# 3. Validasi Model
metrics = model.val()
print("mAP50-95:", metrics.box.map)

# 4. Export ONNX untuk Hot-Swap di Raray Vision
model.export(format="onnx")
"""

    yolo26_code = f"""# ==========================================
# 🔥 GOOGLE COLAB TRAINING PIPELINE (YOLO-26: 200 EPOCHS, T4 GPU)
# Dataset: {folder_name} (Auto-Resume Supported)
# ==========================================
!pip install -q ultralytics pyyaml requests tqdm

# 1. Download & Prepare Dataset Locally
{dataset_setup_script}

# 2. Train YOLO-26 (200 Epochs, T4 GPU dengan Auto-Resume jika Terputus)
from ultralytics import YOLO
import os

last_ckpt = "raray_vision_runs/yolo_26_200epochs/weights/last.pt"
if os.path.exists(last_ckpt):
    print(f"🔄 Checkpoint ditemukan: {{last_ckpt}}! Melanjutkan training (Auto-Resume)...")
    model = YOLO(last_ckpt)
    results = model.train(resume=True)
else:
    print("🔥 Memulai training baru YOLO-26 (200 Epochs)...")
    model = YOLO("yolo11m.pt")
    results = model.train(
        data="data.yaml",
        epochs=200,
        imgsz=640,
        device=0,
        batch=24,
        optimizer="SGD",
        save_period=5,
        project="raray_vision_runs",
        name="yolo_26_200epochs"
    )

# 3. Validasi Model
metrics = model.val()
print("mAP50-95:", metrics.box.map)

# 4. Export ONNX untuk Hot-Swap di Raray Vision
model.export(format="onnx")
"""

    rfdetr_code = f"""# ==========================================
# 🎯 GOOGLE COLAB TRAINING PIPELINE (RF-DETR / RT-DETR: 200 EPOCHS, T4 GPU)
# Dataset: {folder_name} (Auto-Resume Supported)
# ==========================================
!pip install -q ultralytics pyyaml requests tqdm

# 1. Download & Prepare Dataset Locally
{dataset_setup_script}

# 2. Train RF-DETR / RT-DETR (200 Epochs, T4 GPU dengan Auto-Resume jika Terputus)
from ultralytics import RTDETR
import os

last_ckpt = "raray_vision_runs/rfdetr_200epochs/weights/last.pt"
if os.path.exists(last_ckpt):
    print(f"🔄 Checkpoint ditemukan: {{last_ckpt}}! Melanjutkan training (Auto-Resume)...")
    model = RTDETR(last_ckpt)
    results = model.train(resume=True)
else:
    print("🎯 Memulai training baru RF-DETR (200 Epochs)...")
    model = RTDETR("rtdetr-l.pt")
    results = model.train(
        data="data.yaml",
        epochs=200,
        imgsz=640,
        device=0,
        batch=12,
        save_period=5,
        project="raray_vision_runs",
        name="rfdetr_200epochs"
    )

# 3. Validasi Model
metrics = model.val()
print("Validation Results:", metrics)

# 4. Export ONNX untuk Hot-Swap di Raray Vision
model.export(format="onnx")
"""
    return {
        "yolo_code": yolo_code,
        "yolo26_code": yolo26_code,
        "rfdetr_code": rfdetr_code
    }


def generate_colab_notebook_dict(
    folder_name: str,
    yolo_yaml_url: str,
    tasks_url: str,
    coco_url: str,
    model_type: str = "yolox",
    mode: str = "colab",        # "colab" | "local_cpu" | "local_gpu"
    epochs: int = None,          # None = use model default
    batch: int = None,           # None = use model default
    imgsz: int = 640,
    optimizer: str = None,       # None = use model default
    lr0: float = None,           # None = use model default
    workers: int = None,         # None = use platform default
    patience: int = None,        # None = use model default
    weights: str = None,         # None = use model default (e.g. yolo11n.pt, yolo11s.pt, etc.)
    cos_lr: bool = True,         # Cosine learning rate scheduler
    close_mosaic: int = 10,      # Disable mosaic in last N epochs for tight bounding box
    lrf: float = 0.01,           # Final learning rate fraction
    box: float = 7.5,            # Bounding box loss weight (higher = tighter box)
) -> dict:
    # Normalize mode
    mode_norm = mode.lower().replace("-", "_")
    if mode_norm not in ("colab", "local_cpu", "local_gpu"):
        mode_norm = "colab"
    is_local = mode_norm in ("local_cpu", "local_gpu")
    use_cpu = mode_norm == "local_cpu"

    # Normalize model_type
    mt = model_type.lower().replace("-", "").replace("_", "")
    if mt in ["yolox", "yolo11x", "yolo11", "yolo"]:
        model_key = "yolox"
    elif mt in ["yolo26", "yolo26edge", "edge"]:
        model_key = "yolo26"
    elif mt in ["rfdetr", "rtdetr", "detr", "transformer"]:
        model_key = "rfdetr"
    else:
        model_key = "all"

    # Default workers per platform
    default_workers_colab = 4
    default_workers_local = 2

    # Define base model configurations (default values)
    model_configs = {
        "yolox": {
            "title": "⚡ Tutorial & Panduan: Training YOLO-X / YOLO11-X",
            "arch_badge": "⚡ **YOLO-X / YOLO11-X** (High-Performance Real-Time Object Detection)",
            "weights": "yolo11x.pt",
            "run_name_tpl": "yolo_x_{epochs}epochs",
            "epochs": 100 if is_local else 200,
            "imgsz": 640,
            "batch": 8 if use_cpu else 16,
            "optimizer": "AdamW",
            "lr0": 0.001,
            "patience": 30 if is_local else 50,
            "model_desc": "YOLO-X adalah arsitektur model besar untuk akurasi tertinggi dalam deteksi objek real-time.",
            "code_var": "model_yolox",
            "results_var": "results_yolox",
            "metrics_var": "metrics_yolox"
        },
        "yolo26": {
            "title": "🔥 Tutorial & Panduan: Training YOLO-26 (Edge Variant)",
            "arch_badge": "🔥 **YOLO-26 (Fast Edge Variant)** (Ultra Fast Architecture for Edge Devices)",
            "weights": "yolo11m.pt",
            "run_name_tpl": "yolo_26_{epochs}epochs",
            "epochs": 100 if is_local else 200,
            "imgsz": 640,
            "batch": 8 if use_cpu else 24,
            "optimizer": "SGD",
            "lr0": 0.01,
            "patience": 30 if is_local else 50,
            "model_desc": "YOLO-26 dirancang khusus untuk perangkat Edge (Raspberry Pi, Jetson Nano, Mini PC) dengan FPS tinggi.",
            "code_var": "model_yolo26",
            "results_var": "results_yolo26",
            "metrics_var": "metrics_yolo26"
        },
        "rfdetr": {
            "title": "🎯 Tutorial & Panduan: Training RF-DETR / RT-DETR (Transformer)",
            "arch_badge": "🎯 **RF-DETR / RT-DETR** (Real-Time Vision Transformer without NMS)",
            "weights": "rtdetr-l.pt",
            "run_name_tpl": "rfdetr_{epochs}epochs",
            "epochs": 100 if is_local else 200,
            "imgsz": 640,
            "batch": 4 if use_cpu else 12,
            "optimizer": "AdamW",
            "lr0": 0.0001,
            "patience": 30 if is_local else 50,
            "model_desc": "RF-DETR / RT-DETR adalah arsitektur Transformer Vision State-of-the-Art tanpa Non-Maximum Suppression (NMS).",
            "code_var": "model_rfdetr",
            "results_var": "results_rfdetr",
            "metrics_var": "metrics_rfdetr"
        }
    }

    # Apply user overrides to selected model config
    if model_key in model_configs:
        cfg = model_configs[model_key]
        if weights:
            clean_w = weights.strip()
            if not clean_w.endswith(".pt") and not clean_w.endswith(".yaml"):
                clean_w += ".pt"
            cfg["weights"] = clean_w
            w_stem = clean_w.replace(".pt", "").lower()
            cfg["run_name_tpl"] = f"{w_stem}_{{epochs}}epochs"

            # Dynamic scale description
            if w_stem.endswith("n") or "nano" in w_stem:
                scale_desc = "Nano (Ultra-Ringan, Sangat Cocok CPU)"
                default_batch = 16 if use_cpu else 32
            elif w_stem.endswith("s") or "small" in w_stem:
                scale_desc = "Small (Cepat & Akurat)"
                default_batch = 8 if use_cpu else 24
            elif w_stem.endswith("m") or "medium" in w_stem:
                scale_desc = "Medium (Seimbang Speed & Akurasi)"
                default_batch = 8 if use_cpu else 16
            elif w_stem.endswith("l") or "large" in w_stem:
                scale_desc = "Large (Akurasi Tinggi)"
                default_batch = 4 if use_cpu else 12
            elif w_stem.endswith("x") or "xlarge" in w_stem:
                scale_desc = "XLarge (Akurasi Maksimal)"
                default_batch = 4 if use_cpu else 8
            else:
                scale_desc = "Custom Variant"
                default_batch = 8 if use_cpu else 16

            cfg["arch_badge"] = f"⚡ **{clean_w.upper()}** ({scale_desc})"
            cfg["title"] = f"Tutorial & Panduan: Training {clean_w.upper()} ({scale_desc})"
            cfg["model_desc"] = f"Model {clean_w} ({scale_desc}) untuk deteksi objek presisi tinggi."
            if batch is None:
                cfg["batch"] = default_batch

        if epochs is not None:
            cfg["epochs"] = epochs
        if batch is not None:
            cfg["batch"] = batch
        if imgsz is not None:
            cfg["imgsz"] = imgsz
        if optimizer is not None:
            cfg["optimizer"] = optimizer
        if lr0 is not None:
            cfg["lr0"] = lr0
        if patience is not None:
            cfg["patience"] = patience
        cfg["cos_lr"] = bool(cos_lr) if cos_lr is not None else True
        cfg["close_mosaic"] = int(close_mosaic) if close_mosaic is not None else 10
        cfg["lrf"] = float(lrf) if lrf is not None else 0.01
        cfg["box"] = float(box) if box is not None else 7.5
        cfg["workers"] = workers if workers is not None else (default_workers_local if is_local else default_workers_colab)
        cfg["run_name"] = cfg["run_name_tpl"].format(epochs=cfg["epochs"])
        # Build setting_desc dynamically
        hw_label = "CPU Lokal" if use_cpu else ("GPU Lokal (CUDA)" if mode_norm == "local_gpu" else "Tesla T4 GPU (Colab)")
        cfg["setting_desc"] = (
            f"{cfg['weights'].upper()}: {cfg['epochs']} Epochs, Imgsz {cfg['imgsz']}, "
            f"Batch {cfg['batch']}, Optimizer {cfg['optimizer']}, {hw_label}"
        )

    # Compute device expression for training code
    if use_cpu:
        device_expr = "'cpu'"
        device_comment = "CPU (tidak menggunakan GPU)"
    elif mode_norm == "local_gpu":
        device_expr = "0 if torch.cuda.is_available() else 'cpu'"
        device_comment = "GPU CUDA jika tersedia, fallback ke CPU"
    else:
        device_expr = "0"
        device_comment = "GPU 0 (Tesla T4)"

    # Build Header per mode
    if model_key in model_configs:
        cfg = model_configs[model_key]
        if is_local:
            mode_label = "🖥️ Lokal CPU" if use_cpu else "🖥️ Lokal GPU (CUDA)"
            header_text = [
                f"# 🖥️ Notebook Training Lokal PC — {cfg['title']}\n",
                f"**Dataset:** `{folder_name}`  \n",
                f"**Target Model:** {cfg['arch_badge']}  \n",
                f"**Pretrained Base:** `{cfg['weights']}` | **Epochs:** {cfg['epochs']} | **Optimizer:** `{cfg['optimizer']}` | **Batch:** {cfg['batch']}  \n",
                f"**Mode Running:** {mode_label} (Jalankan di Jupyter Notebook / VS Code lokal Anda)  \n",
                f"\n",
                f"---\n",
                f"### ℹ️ Cara Menggunakan Notebook Ini (Lokal PC):\n",
                f"1. Pastikan Python & pip sudah terinstall di PC Anda.\n",
                f"2. Install Jupyter: `pip install jupyter` lalu jalankan `jupyter notebook`.\n",
                f"3. Upload file `.ipynb` ini ke Jupyter, lalu jalankan cell satu per satu.\n",
                f"4. Dataset akan otomatis diunduh dari server ke folder `./dataset/` di PC Anda.\n",
                f"5. Hasil training (best.pt, ONNX) tersimpan di folder `./raray_vision_runs/` lokal.\n",
                f"\n",
                f"> **⚠️ Catatan CPU:** Training pada CPU jauh lebih lambat dari GPU. Untuk dataset besar, pertimbangkan menggunakan mode GPU atau Google Colab T4.",
            ]
        else:
            header_text = [
                f"# {cfg['title']} (Google Colab T4)\n",
                f"**Dataset:** `{folder_name}`  \n",
                f"**Target Model:** {cfg['arch_badge']}  \n",
                f"**Pretrained Base:** `{cfg['weights']}` | **Epochs:** {cfg['epochs']} | **Optimizer:** `{cfg['optimizer']}` | **Batch:** {cfg['batch']}  \n",
                f"**Target Hardware:** NVIDIA T4 GPU (Google Colab Free Tier)  \n",
                f"**Fitur Unggulan:** 🔄 **Auto-Resume Epoch** & 💾 **Google Drive Persistent Cache**  \n",
                f"\n",
                f"---\n",
                f"### 🛡️ Solusi Anti-Terputus (T4 Free Disconnect & Auto-Resume):\n",
                f"Google Colab Free Tier dapat terputus sewaktu-waktu. Notebook ini dilengkapi sistem **Auto-Resume** dan **Penyimpanan Google Drive**:\n",
                f"- **Checkpoint Otomatis (`last.pt`):** Disimpan di Google Drive setiap 5 epoch dan di setiap epoch. Jika runtime Colab terputus di epoch 45, saat dijalankan lagi akan **otomatis melanjutkan ke epoch 46** tanpa mengulang dari 0!\n",
                f"- **Cache Dataset Cepat:** Dataset yang telah diunduh otomatis disimpan di Google Drive (`dataset_{folder_name}.zip`). Sesi berikutnya hanya butuh **10 detik** untuk memulihkan dataset tanpa download ulang!\n",
                f"- **Download Otomatis:** Setelah training selesai, file bobot (`best.pt`) dan evaluasi (.zip) otomatis diunduh ke komputer Anda untuk diunggah ke web **Raray Vision**."
            ]
    else:
        header_text = [

            f"# 📘 Tutorial & Panduan: Training Model Deep Learning di Google Colab\n",
            f"**Dataset:** `{folder_name}`  \n",
            f"**Target Hardware:** NVIDIA T4 GPU (Google Colab Free Tier)  \n",
            f"**Fitur Unggulan:** 🔄 **Auto-Resume Epoch** & 💾 **Google Drive Persistent Cache**  \n",
            f"**Model Didukung:**\n",
            f"1. ⚡ **YOLO-X / YOLO11-X** (High-Performance Real-Time Object Detection)\n",
            f"2. 🔥 **YOLO-26 / Edge Variant** (Ultra Fast Architecture for Edge Devices)\n",
            f"3. 🎯 **RF-DETR / RT-DETR** (Real-Time Transformer Object Detection)\n",
            f"\n",
            f"---\n",
            f"### 🛡️ Solusi Anti-Terputus (T4 Free Disconnect & Auto-Resume):\n",
            f"Google Colab Free Tier dapat terputus sewaktu-waktu. Notebook ini dilengkapi sistem **Auto-Resume** dan **Penyimpanan Google Drive**:\n",
            f"- **Checkpoint Otomatis (`last.pt`):** Disimpan di Google Drive setiap epoch.\n",
            f"- **Cache Dataset Permanen:** Sesi berikutnya hanya butuh **10 detik** untuk memulihkan dataset tanpa download ulang!"
        ]

    cells = []
    cells.append({"cell_type": "markdown", "metadata": {}, "source": header_text})

    # ── Steps 0 through 7 (Common Preparation, mode-aware) ──────────────────
    cells.extend([
        # LANGKAH 0: CEK STATUS HARDWARE
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": (
                [
                    "### 🖥️ Langkah 0: Cek Status Hardware (CPU/GPU)\n",
                    "Memeriksa ketersediaan GPU CUDA di PC Anda."
                ] if is_local else [
                    "### 🖥️ Langkah 0: Cek Akses GPU (Runtime Check)\n",
                    "Memastikan runtime Google Colab menggunakan **GPU Tesla T4** agar proses training berjalan cepat."
                ]
            )
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": (
                [
                    "import torch\n",
                    "import subprocess\n",
                    "\n",
                    "print('=== STATUS HARDWARE LOKAL ===')\n",
                    "gpu_available = torch.cuda.is_available()\n",
                    "if gpu_available:\n",
                    "    device_name = torch.cuda.get_device_name(0)\n",
                    "    print(f'[OK] GPU CUDA Terdeteksi: {device_name}')\n",
                    "    try:\n",
                    "        gpu_info = subprocess.check_output('nvidia-smi', shell=True).decode('utf-8')\n",
                    "        print(gpu_info)\n",
                    "    except Exception:\n",
                    "        print('nvidia-smi tidak tersedia, namun GPU CUDA aktif.')\n",
                    "else:\n",
                    "    print('[INFO] GPU CUDA tidak terdeteksi. Training akan berjalan di CPU.')\n",
                    f"print('[INFO] Device yang akan digunakan: {device_comment}')\n",
                ] if is_local else [
                    "# Cek apakah GPU tersedia menggunakan PyTorch dan command nvidia-smi\n",
                    "import torch\n",
                    "import subprocess\n",
                    "\n",
                    "gpu_available = torch.cuda.is_available()\n",
                    "print('=== STATUS RUNTIME GOOGLE COLAB ===')\n",
                    "if gpu_available:\n",
                    "    device_name = torch.cuda.get_device_name(0)\n",
                    "    print(f'[OK] GPU Terdeteksi: {device_name}')\n",
                    "    print('\\nDetail Spesifikasi GPU:')\n",
                    "    try:\n",
                    "        gpu_info = subprocess.check_output('nvidia-smi', shell=True).decode('utf-8')\n",
                    "        print(gpu_info)\n",
                    "    except Exception:\n",
                    "        print('Tidak dapat memanggil nvidia-smi, namun GPU CUDA tetap aktif.')\n",
                    "else:\n",
                    "    print('[WARNING] GPU tidak terdeteksi! Silakan ganti runtime ke T4 GPU via menu: Runtime > Change runtime type > T4 GPU.')\n",
                ]
            )
        },
    ])

    # LANGKAH 0B: GOOGLE DRIVE (Colab only) or LOCAL SETUP (local mode)
    if is_local:
        cells.extend([
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "### 📁 Langkah 0B: Setup Direktori Lokal\n",
                    "Menyiapkan folder output untuk menyimpan checkpoint dan hasil training di PC Anda."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "import os\n",
                    "\n",
                    f"folder_name = '{folder_name}'\n",
                    "# Folder output training tersimpan di sini (relatif dari lokasi notebook ini)\n",
                    "RUNS_DIR = os.path.abspath('raray_vision_runs')\n",
                    "os.makedirs(RUNS_DIR, exist_ok=True)\n",
                    "print(f'[OK] Folder output training: {RUNS_DIR}')\n",
                    "print('[OK] Tidak memerlukan Google Drive — semua file tersimpan lokal!')\n",
                ]
            },
        ])
    else:
        cells.extend([
            # LANGKAH 0B: GOOGLE DRIVE MOUNT
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "### 💾 Langkah 0B: Hubungkan Google Drive (Penyimpanan Permanen & Anti-Disconnect)\n",
                    "**Langkah ini sangat penting untuk Colab Free Tier!**\n",
                    "Menyambungkan Google Drive Anda agar checkpoint (`last.pt`) dan cache dataset tersimpan permanen.\n",
                    "Jika runtime Google Colab terputus di tengah jalan, Anda tidak akan kehilangan progres training sama sekali."
                ]
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# Mount Google Drive untuk penyimpanan permanen checkpoint & cache dataset\n",
                    "import os\n",
                    "\n",
                    f"folder_name = '{folder_name}'\n",
                    "USE_GOOGLE_DRIVE = True  # Ubah ke False jika HANYA ingin menyimpan di disk sementara Colab\n",
                    "DRIVE_BASE_DIR = '/content/drive/MyDrive/raray_vision_colab'\n",
                    "DRIVE_RUNS_DIR = os.path.join(DRIVE_BASE_DIR, 'runs')\n",
                    "DRIVE_DATASET_ZIP = os.path.join(DRIVE_BASE_DIR, f'dataset_{folder_name}.zip')\n",
                    "\n",
                    "if USE_GOOGLE_DRIVE:\n",
                    "    try:\n",
                    "        from google.colab import drive\n",
                    "        print('Menghubungkan ke Google Drive...')\n",
                    "        drive.mount('/content/drive')\n",
                    "        os.makedirs(DRIVE_RUNS_DIR, exist_ok=True)\n",
                    "        print(f'[OK] Google Drive terhubung! Folder proyek: {DRIVE_BASE_DIR}')\n",
                    "        print(f'[OK] Folder Checkpoint Runs: {DRIVE_RUNS_DIR}')\n",
                    "    except Exception as e:\n",
                    "        print(f'[WARNING] Google Drive tidak tersambung ({e}). Menggunakan penyimpanan lokal Colab.')\n",
                    "        USE_GOOGLE_DRIVE = False\n",
                    "        DRIVE_RUNS_DIR = 'raray_vision_runs'\n",
                    "else:\n",
                    "    print('Google Drive dinonaktifkan. Menggunakan penyimpanan lokal Colab.')\n",
                    "    DRIVE_RUNS_DIR = 'raray_vision_runs'\n",
                ]
            },
        ])

    cells.extend([
        # LANGKAH 1: INSTALL DEPENDENCIES
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 📦 Langkah 1: Instalasi Library & Dependensi\n",
                "Menginstal library resmi yang diperlukan: **Ultralytics** (YOLO11, YOLO-X, YOLO-26, RT-DETR), **PyYAML**, dan library pendukung."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Install library Ultralytics dan dependensi pendukung\n",
                "import subprocess, sys\n",
                "subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', '--upgrade',\n",
                "                       'ultralytics', 'pyyaml', 'requests', 'tqdm', 'pillow'])\n",
                "\n",
                "import ultralytics\n",
                "print(f'[OK] Ultralytics Version: {ultralytics.__version__}')\n",
                "ultralytics.checks()\n",
            ]
        },
        # LANGKAH 2: STRUKTUR DIREKTORI & CEK CACHE
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": (
                [
                    "### 📁 Langkah 2: Menyiapkan Struktur Direktori Dataset (Lokal)\n",
                    "Menyiapkan folder `./dataset/images/train`, `./dataset/images/val`, dll di PC Anda."
                ] if is_local else [
                    "### 📁 Langkah 2: Menyiapkan Struktur Direktori & Cek Cache Dataset di Google Drive\n",
                    "Menyiapkan folder lokal di Colab (`/content/dataset/images/train`, `/content/dataset/images/val`, dll) dan memeriksa apakah dataset sudah pernah disimpan di Google Drive.\n",
                    "**Jika sudah ada di Google Drive**, dataset akan diekstrak langsung dalam ~10 detik tanpa perlu download ulang!"
                ]
            )
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": (
                [
                    "import os, glob, shutil, time, json, zipfile\n",
                    "\n",
                    "# Inisialisasi struktur direktori YOLO di lokal\n",
                    "base_dir = os.path.abspath('dataset')\n",
                    "train_img_dir = os.path.join(base_dir, 'images', 'train')\n",
                    "val_img_dir = os.path.join(base_dir, 'images', 'val')\n",
                    "train_lbl_dir = os.path.join(base_dir, 'labels', 'train')\n",
                    "val_lbl_dir = os.path.join(base_dir, 'labels', 'val')\n",
                    "\n",
                    "for d in [train_img_dir, val_img_dir, train_lbl_dir, val_lbl_dir]:\n",
                    "    os.makedirs(d, exist_ok=True)\n",
                    "\n",
                    "DATASET_RESTORED_FROM_CACHE = False\n",
                    "print(f'[OK] Direktori dataset lokal siap: {base_dir}')\n",
                ] if is_local else [
                    "import os, glob, shutil, time, json, zipfile\n",
                    "\n",
                    "# Inisialisasi struktur direktori YOLO di Colab\n",
                    "base_dir = os.path.abspath('dataset')\n",
                    "train_img_dir = os.path.join(base_dir, 'images', 'train')\n",
                    "val_img_dir = os.path.join(base_dir, 'images', 'val')\n",
                    "train_lbl_dir = os.path.join(base_dir, 'labels', 'train')\n",
                    "val_lbl_dir = os.path.join(base_dir, 'labels', 'val')\n",
                    "\n",
                    "for d in [train_img_dir, val_img_dir, train_lbl_dir, val_lbl_dir]:\n",
                    "    os.makedirs(d, exist_ok=True)\n",
                    "\n",
                    "DATASET_RESTORED_FROM_CACHE = False\n",
                    "\n",
                    "# Cek apakah arsip dataset sudah tersimpan di Google Drive\n",
                    "if 'DRIVE_DATASET_ZIP' in locals() and os.path.exists(DRIVE_DATASET_ZIP):\n",
                    "    print(f'[OK] DITEMUKAN CACHE DATASET DI GOOGLE DRIVE: {DRIVE_DATASET_ZIP}')\n",
                    "    print('Mengekstrak dataset langsung ke Colab (~10 detik, anti-download ulang)...')\n",
                    "    with zipfile.ZipFile(DRIVE_DATASET_ZIP, 'r') as zf:\n",
                    "        zf.extractall('/content')\n",
                    "    \n",
                    "    train_imgs = len(glob.glob(os.path.join(train_img_dir, '*.*')))\n",
                    "    val_imgs = len(glob.glob(os.path.join(val_img_dir, '*.*')))\n",
                    "    print(f'[OK] Dataset sukses dipulihkan dari cache Drive! (Train: {train_imgs}, Val: {val_imgs} gambar)')\n",
                    "    if train_imgs > 0:\n",
                    "        DATASET_RESTORED_FROM_CACHE = True\n",
                    "else:\n",
                    "    print('[INFO] Cache dataset di Google Drive belum ada. Sistem akan mengunduh dan menyimpannya otomatis di Langkah 6.')\n",
                ]
            )
        },
        # LANGKAH 3: HELPER DOWNLOAD
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 🛠️ Langkah 3: Inisialisasi Download Helper (Anti-Timeout, Chunking & Auto-Retry)\n",
                "Menyiapkan helper download dengan connection pooling, header browser, dan chunked streaming untuk mengatasi file gambar berukuran besar dan koneksi jaringan lambat."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import requests\n",
                "from requests.adapters import HTTPAdapter\n",
                "from urllib3.util.retry import Retry\n",
                "\n",
                "session = requests.Session()\n",
                "retries = Retry(\n",
                "    total=7,\n",
                "    backoff_factor=1.5,\n",
                "    status_forcelist=[429, 500, 502, 503, 504],\n",
                "    raise_on_status=False\n",
                ")\n",
                "adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)\n",
                "session.mount('https://', adapter)\n",
                "session.mount('http://', adapter)\n",
                "\n",
                "HEADERS = {\n",
                "    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'\n",
                "}\n",
                "\n",
                f"PUBLIC_APP_URL = '{PUBLIC_APP_URL}'\n",
                "\n",
                "def get_direct_url(url):\n",
                "    if not url:\n",
                "        return url\n",
                "    if '/api/v1/storage/proxy?url=' in url:\n",
                "        raw_part = url.split('/api/v1/storage/proxy?url=', 1)[1]\n",
                "        from urllib.parse import unquote\n",
                "        url = unquote(raw_part)\n",
                "    if 'is3.cloudhost.id/onechitra/upload/' in url:\n",
                "        url = url.replace('https://is3.cloudhost.id/onechitra/upload/', f'{PUBLIC_APP_URL}/api/v1/uploads/upload/')\n",
                "        url = url.replace('http://is3.cloudhost.id/onechitra/upload/', f'{PUBLIC_APP_URL}/api/v1/uploads/upload/')\n",
                "    if '127.0.0.1:8000' in url:\n",
                "        url = url.replace('http://127.0.0.1:8000', PUBLIC_APP_URL)\n",
                "    if 'localhost:8000' in url:\n",
                "        url = url.replace('http://localhost:8000', PUBLIC_APP_URL)\n",
                "    if url.startswith('/'):\n",
                "        return f'{PUBLIC_APP_URL}{url}'\n",
                "    return url\n",
                "\n",
                "def robust_download_file(url, target_path, timeout=(15, 60)):\n",
                "    url = get_direct_url(url)\n",
                "    for attempt in range(4):\n",
                "        try:\n",
                "            resp = session.get(url, headers=HEADERS, timeout=timeout, stream=True)\n",
                "            if resp.status_code == 200:\n",
                "                with open(target_path, 'wb') as f:\n",
                "                    for chunk in resp.iter_content(chunk_size=131072):\n",
                "                        if chunk:\n",
                "                            f.write(chunk)\n",
                "                if os.path.exists(target_path) and os.path.getsize(target_path) > 0:\n",
                "                    return True\n",
                "        except Exception:\n",
                "            time.sleep(1)\n",
                "    return False\n",
                "\n",
                "print('[OK] Helper download robust siap digunakan.')\n",
            ]
        },
        # LANGKAH 4: DATA.YAML
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### ⚙️ Langkah 4: Download & Setup Konfigurasi `data.yaml`\n",
                "Mengunduh file konfigurasi `data.yaml` yang berisi daftar kelas dan path folder dataset."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import yaml\n",
                "\n",
                f"yaml_url = '{yolo_yaml_url}'\n",
                "print(f'Mengunduh data.yaml dari: {yaml_url}')\n",
                "\n",
                "success = robust_download_file(yaml_url, 'data.yaml', timeout=(10, 30))\n",
                "if not success or not os.path.exists('data.yaml') or os.path.getsize('data.yaml') == 0:\n",
                "    print('⚠ Menggunakan template data.yaml darurat...')\n",
                "    fallback_yaml = {\n",
                "        'path': os.path.abspath('dataset'),\n",
                "        'train': 'images/train',\n",
                "        'val': 'images/val',\n",
                "        'names': {0: 'defect'}\n",
                "    }\n",
                "    with open('data.yaml', 'w') as f:\n",
                "        yaml.dump(fallback_yaml, f, sort_keys=False)\n",
                "else:\n",
                "    with open('data.yaml', 'r') as f:\n",
                "        ydata = yaml.safe_load(f)\n",
                "    ydata['path'] = os.path.abspath('dataset')\n",
                "    ydata['train'] = 'images/train'\n",
                "    ydata['val'] = 'images/val'\n",
                "    with open('data.yaml', 'w') as f:\n",
                "        yaml.dump(ydata, f, sort_keys=False)\n",
                "\n",
                "print('[OK] Konfigurasi data.yaml siap:')\n",
                "with open('data.yaml', 'r') as f:\n",
                "    print(f.read().strip())\n",
            ]
        },
        # LANGKAH 5: FETCH TASKS
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 📑 Langkah 5: Download Anotasi Dataset (Tasks JSON)\n",
                "Mengambil daftar task anotasi (bounding box, label, dan link gambar)."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                f"tasks_url = '{tasks_url}'\n",
                f"coco_url = '{coco_url}'\n",
                "if 'get_direct_url' in globals():\n",
                "    tasks_url = get_direct_url(tasks_url)\n",
                "    coco_url = get_direct_url(coco_url)\n",
                "print(f'Mengunduh anotasi tasks dari: {tasks_url}')\n",
                "\n",
                "tasks_data = None\n",
                "for attempt in range(5):\n",
                "    try:\n",
                "        r = session.get(tasks_url, headers=HEADERS, timeout=(15, 60))\n",
                "        if r.status_code == 200:\n",
                "            tasks_data = r.json()\n",
                "            break\n",
                "    except Exception as e:\n",
                "        print(f'Percobaan {attempt+1} gagal: {e}. Mengulang dalam 2 detik...')\n",
                "        time.sleep(2)\n",
                "\n",
                "# Fallback otomatis ke COCO annotations jika tasks_url tidak merespon\n",
                "if not tasks_data:\n",
                "    print('⚠ Mencoba memuat dari file annotations_coco.json sebagai alternatif...')\n",
                "    try:\n",
                "        r_coco = session.get(coco_url, headers=HEADERS, timeout=(15, 60))\n",
                "        if r_coco.status_code == 200:\n",
                "            coco_json = r_coco.json()\n",
                "            id_to_img = {img['id']: img for img in coco_json.get('images', [])}\n",
                "            id_to_cat = {c['id']: c.get('name', 'defect') for c in coco_json.get('categories', [])}\n",
                "            ann_by_img = {}\n",
                "            for ann in coco_json.get('annotations', []):\n",
                "                ann_by_img.setdefault(ann['image_id'], []).append(ann)\n",
                "            \n",
                "            tasks_data = []\n",
                "            for img_id, img_info in id_to_img.items():\n",
                "                fname = img_info.get('file_name', '')\n",
                "                w = img_info.get('width', 1) or 1\n",
                "                h = img_info.get('height', 1) or 1\n",
                f"                t_img_url = f'{{PUBLIC_APP_URL}}/api/v1/uploads/upload/datasets/{folder_name}/images/{{fname}}'\n",
                "                res_list = []\n",
                "                for a in ann_by_img.get(img_id, []):\n",
                "                    bbox = a.get('bbox', [0, 0, 0, 0])\n",
                "                    bx, by, bw, bh = bbox[0], bbox[1], bbox[2], bbox[3]\n",
                "                    cat_name = id_to_cat.get(a.get('category_id'), 'defect')\n",
                "                    res_list.append({\n",
                "                        'type': 'rectanglelabels',\n",
                "                        'value': {\n",
                "                            'x': (bx / w) * 100.0,\n",
                "                            'y': (by / h) * 100.0,\n",
                "                            'width': (bw / w) * 100.0,\n",
                "                            'height': (bh / h) * 100.0,\n",
                "                            'rectanglelabels': [cat_name]\n",
                "                        }\n",
                "                    })\n",
                "                tasks_data.append({\n",
                "                    'data': {'image': t_img_url, 'original_filename': fname},\n",
                "                    'annotations': [{'result': res_list}]\n",
                "                })\n",
                "            print(f'[OK] Berhasil memuat {len(tasks_data)} tasks dari file COCO!')\n",
                "    except Exception as e:\n",
                "        print(f'Fallback COCO juga gagal: {e}')\n",
                "\n",
                "if tasks_data:\n",
                "    print(f'[OK] Total tasks anotasi siap: {len(tasks_data)}')\n",
                "else:\n",
                "    print('[WARNING] Gagal mengunduh tasks_data!')\n",
                "    tasks_data = []\n",
            ]
        },
        # LANGKAH 6: DOWNLOAD GAMBAR
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": (
                [
                    "### 📥 Langkah 6: Download Gambar Dataset ke Lokal\n",
                    "Sistem akan mengunduh gambar menggunakan multi-threading ke folder `./dataset/` di PC Anda."
                ] if is_local else [
                    "### 📥 Langkah 6: Download Gambar & Pembuatan Cache di Google Drive\n",
                    "Jika dataset sudah dipulihkan dari Google Drive di Langkah 2, langkah ini akan **otomatis melompat** (selesai dalam 1 detik).\n",
                    "Jika belum, sistem akan mengunduh gambar menggunakan multi-threading dan langsung mengarsipkannya ke Google Drive."
                ]
            )
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": (
                [
                    "from concurrent.futures import ThreadPoolExecutor\n",
                    "from tqdm import tqdm\n",
                    "\n",
                    "print(f'Memulai download {len(tasks_data)} gambar ke direktori lokal...')\n",
                    "\n",
                    "# Build class mapping dari data.yaml\n",
                    "with open('data.yaml', 'r') as f:\n",
                    "    yaml_cfg = yaml.safe_load(f)\n",
                    "class_names = yaml_cfg.get('names', {0: 'defect'})\n",
                    "if isinstance(class_names, list):\n",
                    "    name_to_idx = {name: idx for idx, name in enumerate(class_names)}\n",
                    "elif isinstance(class_names, dict):\n",
                    "    name_to_idx = {name: int(idx) for idx, name in class_names.items()}\n",
                    "else:\n",
                    "    name_to_idx = {}\n",
                    "\n",
                    "def process_task(task_idx, task):\n",
                    "    try:\n",
                    "        img_url = task.get('data', {}).get('image') or task.get('image')\n",
                    "        if not img_url:\n",
                    "            return\n",
                    "        is_val = (task_idx % 5 == 0)\n",
                    "        split = 'val' if is_val else 'train'\n",
                    "        \n",
                    "        fname = os.path.basename(img_url).split('?')[0]\n",
                    "        if not fname:\n",
                    "            fname = f'img_{task_idx}.jpg'\n",
                    "        ext = os.path.splitext(fname)[1] or '.jpg'\n",
                    "        base_name = os.path.splitext(fname)[0]\n",
                    "        \n",
                    "        img_save_path = os.path.join(base_dir, 'images', split, f'{base_name}{ext}')\n",
                    "        lbl_save_path = os.path.join(base_dir, 'labels', split, f'{base_name}.txt')\n",
                    "        \n",
                    "        if not os.path.exists(img_save_path) or os.path.getsize(img_save_path) == 0:\n",
                    "            robust_download_file(img_url, img_save_path)\n",
                    "        \n",
                    "        # Tulis label YOLO\n",
                    "        labels = []\n",
                    "        for ann in task.get('annotations', []):\n",
                    "            for res in ann.get('result', []):\n",
                    "                if res.get('type') == 'rectanglelabels':\n",
                    "                    val = res.get('value', {})\n",
                    "                    lbl_name = val.get('rectanglelabels', ['defect'])[0]\n",
                    "                    cls_id = name_to_idx.get(lbl_name, 0)\n",
                    "                    x = (val.get('x', 0) + val.get('width', 0) / 2) / 100.0\n",
                    "                    y = (val.get('y', 0) + val.get('height', 0) / 2) / 100.0\n",
                    "                    w = val.get('width', 0) / 100.0\n",
                    "                    h = val.get('height', 0) / 100.0\n",
                    "                    labels.append(f'{cls_id} {x:.6f} {y:.6f} {w:.6f} {h:.6f}')\n",
                    "        \n",
                    "        with open(lbl_save_path, 'w') as lf:\n",
                    "            lf.write('\\n'.join(labels))\n",
                    "    except Exception:\n",
                    "        pass\n",
                    "\n",
                    "with ThreadPoolExecutor(max_workers=4) as executor:\n",
                    "    list(tqdm(executor.map(lambda item: process_task(item[0], item[1]), enumerate(tasks_data)), total=len(tasks_data), desc='Downloading Dataset'))\n",
                    "\n",
                    "print('[OK] Download dataset selesai!')\n",
                ] if is_local else [
                    "from concurrent.futures import ThreadPoolExecutor\n",
                    "from tqdm import tqdm\n",
                    "\n",
                    "if DATASET_RESTORED_FROM_CACHE:\n",
                    "    print('⚡ Dataset sudah lengkap dipulihkan dari cache Google Drive!')\n",
                    "    print('Melompati proses download gambar.')\n",
                    "else:\n",
                    "    print(f'Memulai download {len(tasks_data)} gambar...')\n",
                    "    \n",
                    "    # Build class mapping dari data.yaml\n",
                    "    with open('data.yaml', 'r') as f:\n",
                    "        yaml_cfg = yaml.safe_load(f)\n",
                    "    class_names = yaml_cfg.get('names', {0: 'defect'})\n",
                    "    if isinstance(class_names, list):\n",
                    "        name_to_idx = {name: idx for idx, name in enumerate(class_names)}\n",
                    "    elif isinstance(class_names, dict):\n",
                    "        name_to_idx = {name: int(idx) for idx, name in class_names.items()}\n",
                    "    else:\n",
                    "        name_to_idx = {}\n",
                    "\n",
                    "    def process_task(task_idx, task):\n",
                    "        try:\n",
                    "            img_url = task.get('data', {}).get('image') or task.get('image')\n",
                    "            if not img_url:\n",
                    "                return\n",
                    "            is_val = (task_idx % 5 == 0)\n",
                    "            split = 'val' if is_val else 'train'\n",
                    "            \n",
                    "            fname = os.path.basename(img_url).split('?')[0]\n",
                    "            if not fname:\n",
                    "                fname = f'img_{task_idx}.jpg'\n",
                    "            ext = os.path.splitext(fname)[1] or '.jpg'\n",
                    "            base_name = os.path.splitext(fname)[0]\n",
                    "            \n",
                    "            img_save_path = os.path.join(base_dir, 'images', split, f'{base_name}{ext}')\n",
                    "            lbl_save_path = os.path.join(base_dir, 'labels', split, f'{base_name}.txt')\n",
                    "            \n",
                    "            if not os.path.exists(img_save_path) or os.path.getsize(img_save_path) == 0:\n",
                    "                robust_download_file(img_url, img_save_path)\n",
                    "            \n",
                    "            # Tulis label YOLO\n",
                    "            labels = []\n",
                    "            for ann in task.get('annotations', []):\n",
                    "                for res in ann.get('result', []):\n",
                    "                    if res.get('type') == 'rectanglelabels':\n",
                    "                        val = res.get('value', {})\n",
                    "                        lbl_name = val.get('rectanglelabels', ['defect'])[0]\n",
                    "                        cls_id = name_to_idx.get(lbl_name, 0)\n",
                    "                        x = (val.get('x', 0) + val.get('width', 0) / 2) / 100.0\n",
                    "                        y = (val.get('y', 0) + val.get('height', 0) / 2) / 100.0\n",
                    "                        w = val.get('width', 0) / 100.0\n",
                    "                        h = val.get('height', 0) / 100.0\n",
                    "                        labels.append(f'{cls_id} {x:.6f} {y:.6f} {w:.6f} {h:.6f}')\n",
                    "            \n",
                    "            with open(lbl_save_path, 'w') as lf:\n",
                    "                lf.write('\\n'.join(labels))\n",
                    "        except Exception:\n",
                    "            pass\n",
                    "\n",
                    "    with ThreadPoolExecutor(max_workers=8) as executor:\n",
                    "        list(tqdm(executor.map(lambda item: process_task(item[0], item[1]), enumerate(tasks_data)), total=len(tasks_data), desc='Downloading Dataset'))\n",
                    "    \n",
                    "    # Auto-Cache ke Google Drive jika terhubung\n",
                    "    if 'USE_GOOGLE_DRIVE' in locals() and USE_GOOGLE_DRIVE and 'DRIVE_DATASET_ZIP' in locals():\n",
                    "        print('\\n💾 Mengarsipkan dataset ke Google Drive untuk proteksi disconnect...')\n",
                    "        try:\n",
                    "            with zipfile.ZipFile(DRIVE_DATASET_ZIP, 'w', zipfile.ZIP_DEFLATED) as zf:\n",
                    "                for root, _, files in os.walk(base_dir):\n",
                    "                    for f in files:\n",
                    "                        full_p = os.path.join(root, f)\n",
                    "                        rel_p = os.path.relpath(full_p, '/content')\n",
                    "                        zf.write(full_p, arcname=rel_p)\n",
                    "            print(f'[OK] Cache dataset tersimpan permanen di Google Drive: {DRIVE_DATASET_ZIP}')\n",
                    "        except Exception as e:\n",
                    "            print(f'Gagal mengarsipkan dataset ke Drive: {e}')\n",
                ]
            )
        },
        # LANGKAH 7: VERIFIKASI INTEGRITAS
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 🔍 Langkah 7: Verifikasi Integritas Dataset\n",
                "Memeriksa jumlah file gambar dan label di folder train dan val untuk memastikan dataset 100% siap ditraining."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "train_imgs = glob.glob(os.path.join(train_img_dir, '*.*'))\n",
                "val_imgs = glob.glob(os.path.join(val_img_dir, '*.*'))\n",
                "train_lbls = glob.glob(os.path.join(train_lbl_dir, '*.txt'))\n",
                "val_lbls = glob.glob(os.path.join(val_lbl_dir, '*.txt'))\n",
                "\n",
                "print('=== RINGKASAN DATASET SIAP TRAINING ===')\n",
                "print(f'Images Train : {len(train_imgs)} gambar')\n",
                "print(f'Labels Train : {len(train_lbls)} file anotasi')\n",
                "print(f'Images Val   : {len(val_imgs)} gambar')\n",
                "print(f'Labels Val   : {len(val_lbls)} file anotasi')\n",
                "\n",
                "if len(train_imgs) == 0:\n",
                "    print('[WARNING] Gambar train masih kosong! Periksa koneksi atau langkah download di atas.')\n",
                "else:\n",
                "    print('[OK] Dataset 100% Siap untuk Training!')\n",
            ]
        }
    ])

    # ── Model-specific cells (Step 8, 9, 10) ────────────────────────────────

    if model_key in model_configs:
        cfg = model_configs[model_key]
        is_detr = "detr" in cfg["weights"].lower()
        import_stmt = "from ultralytics import RTDETR" if is_detr else "from ultralytics import YOLO"
        model_cls = "RTDETR" if is_detr else "YOLO"
        
        # Training Step (Langkah 8)
        auto_resume_note = (
            f"- **🔄 Auto-Resume:** Jika training terhenti, jalankan kembali cell ini! Sistem akan otomatis mendeteksi `last.pt` dan melanjutkan dari epoch terakhir."
            if is_local else
            f"- **🔄 Auto-Resume:** Jika Colab terputus, jalankan kembali cell ini! Sistem akan otomatis mendeteksi `last.pt` dan melanjutkan dari epoch terakhir tanpa mengulang dari 0."
        )
        hw_note = f"🖥️ Mode: {'CPU Lokal' if use_cpu else ('GPU Lokal (CUDA)' if mode_norm == 'local_gpu' else 'Google Colab T4 GPU')}"
        cells.append({
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                f"### 🚀 Langkah 8: Training Model {cfg['arch_badge']}\n",
                f"{cfg['model_desc']}\n",
                f"- **Pretrained Base:** `{cfg['weights']}`\n",
                f"- **Epochs:** `{cfg['epochs']}`\n",
                f"- **Optimizer:** `{cfg['optimizer']}`\n",
                f"- **Batch Size:** `{cfg['batch']}`\n",
                f"- **Image Size:** `{cfg['imgsz']}`\n",
                f"- **Akurasi & Tuning:** `cos_lr={cfg['cos_lr']}` | `close_mosaic={cfg['close_mosaic']}` | `box_loss={cfg['box']}`\n",
                f"- **{hw_note}**\n",
                auto_resume_note
            ]
        })
        runs_dir_expr = "RUNS_DIR" if is_local else "DRIVE_RUNS_DIR if ('USE_GOOGLE_DRIVE' in locals() and USE_GOOGLE_DRIVE and os.path.exists('/content/drive/MyDrive')) else 'raray_vision_runs'"
        cells.append({
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                f"{import_stmt}\n",
                "import torch\n",
                "\n",
                f"# Tentukan folder output penyimpanan\n",
                f"runs_output_dir = {runs_dir_expr}\n",
                f"run_name = '{cfg['run_name']}'\n",
                "\n",
                "# Cek keberadaan file checkpoint last.pt untuk Auto-Resume\n",
                "ckpt_path = os.path.join(runs_output_dir, run_name, 'weights', 'last.pt')\n",
                "if not os.path.exists(ckpt_path):\n",
                "    local_ckpt = os.path.join('raray_vision_runs', run_name, 'weights', 'last.pt')\n",
                "    if os.path.exists(local_ckpt):\n",
                "        ckpt_path = local_ckpt\n",
                "\n",
                "if os.path.exists(ckpt_path):\n",
                "    print('==================================================================')\n",
                "    print(f'🔄 CHECKPOINT TERAKHIR DITEMUKAN: {ckpt_path}')\n",
                f"    print('⚡ MELANJUTKAN TRAINING {model_key.upper()} DARI EPOCH TERAKHIR (AUTO-RESUME)...')\n",
                "    print('==================================================================')\n",
                f"    {cfg['code_var']} = {model_cls}(ckpt_path)\n",
                f"    {cfg['results_var']} = {cfg['code_var']}.train(resume=True)\n",
                "else:\n",
                f"    print('🚀 MEMULAI TRAINING BARU {model_key.upper()} ({cfg['epochs']} EPOCHS)...')\n",
                f"    print(f'📁 Lokasi penyimpanan weights: {{runs_output_dir}}/{{run_name}}')\n",
                f"    {cfg['code_var']} = {model_cls}('{cfg['weights']}')\n",
                f"    {cfg['results_var']} = {cfg['code_var']}.train(\n",
                "        data='data.yaml',\n",
                f"        epochs={cfg['epochs']},\n",
                f"        imgsz={cfg['imgsz']},\n",
                f"        batch={cfg['batch']},\n",
                f"        device={device_expr},  # {device_comment}\n",
                f"        workers={cfg['workers']},\n",
                f"        optimizer='{cfg['optimizer']}',\n",
                f"        lr0={cfg['lr0']},\n",
                f"        lrf={cfg['lrf']},\n",
                f"        cos_lr={cfg['cos_lr']},\n",
                f"        close_mosaic={cfg['close_mosaic']},\n",
                f"        box={cfg['box']},\n",
                f"        patience={cfg['patience']},\n",
                "        save=True,\n",
                "        save_period=5,  # Simpan checkpoint berkala setiap 5 epoch\n",
                "        project=runs_output_dir,\n",
                "        name=run_name\n",
                "    )\n",
                "\n",
                f"print('\\n📊 VALIDASI {model_key.upper()}:')\n",
                f"{cfg['metrics_var']} = {cfg['code_var']}.val()\n",
                f"print('Validation mAP50:', getattr(getattr({cfg['metrics_var']}, 'box', None), 'map50', 'N/A'))\n",
                "\n",
                "# Export ke format ONNX\n",
                f"{cfg['code_var']}.export(format='onnx', dynamic=True, simplify=True)\n",
                f"print('✓ {model_key.upper()} weights & ONNX berhasil diekspor!')\n"
            ]
        })

        # Packaging Step (Langkah 9)
        cells.append({
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                f"### 📦 Langkah 9: Pengemasan Bobot Model & Hasil Evaluasi ({model_key.upper()})\n",
                "Tahap ini mengumpulkan file bobot terbaik (`best.pt`), bobot ONNX (`best.onnx`), kurva metrik, confusion matrix, dan `results.csv` ke dalam arsip ZIP yang rapi.\n",
                "Mencari file training di folder Google Drive maupun folder lokal Colab secara otomatis."
            ]
        })
        cells.append({
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# ==========================================================\n",
                "# PENGATURAN METADATA & ARSIP ZIP TRAINING\n",
                "# ==========================================================\n",
                "import os, glob, shutil, json, zipfile\n",
                "from datetime import datetime\n",
                "\n",
                "# 📝 Masukkan tanggal dan keterangan setting model Anda:\n",
                "TANGGAL_TRAINING = datetime.now().strftime('%Y-%m-%d')  # Format: YYYY-MM-DD\n",
                f"KETERANGAN_SETTING = '{cfg['setting_desc']}'\n",
                "\n",
                f"print('=== PENGEMASAN ARSIP EVALUASI & BOBOT MODEL ({model_key.upper()}) ===')\n",
                "# Cari run training di Google Drive dan raray_vision_runs lokal\n",
                "search_dirs = []\n",
                "if 'DRIVE_RUNS_DIR' in locals() and os.path.exists(DRIVE_RUNS_DIR):\n",
                f"    search_dirs.extend(glob.glob(f'{{DRIVE_RUNS_DIR}}/{cfg['run_name']}*'))\n",
                f"search_dirs.extend(glob.glob('raray_vision_runs/{cfg['run_name']}*'))\n",
                "valid_runs = [r for r in search_dirs if os.path.isdir(r) and not r.endswith('.zip')]\n",
                "all_runs = sorted(list(set(valid_runs)), key=os.path.getmtime, reverse=True)\n",
                "\n",
                "if not all_runs:\n",
                "    print('❌ Belum ada folder hasil training ditemukan. Silakan jalankan cell Langkah 8 terlebih dahulu.')\n",
                "else:\n",
                "    latest_run = all_runs[0]\n",
                "    run_name = os.path.basename(latest_run)\n",
                "    print(f'📁 Direktori Training Terpilih: {latest_run}')\n",
                "    \n",
                "    # 1. Buat file metadata setting training\n",
                "    meta_info = {\n",
                "        'training_date': TANGGAL_TRAINING,\n",
                "        'training_settings': KETERANGAN_SETTING,\n",
                f"        'model_architecture': '{model_key.upper()}',\n",
                "        'run_name': run_name,\n",
                "        'created_at': datetime.now().isoformat()\n",
                "    }\n",
                "    meta_path = os.path.join(latest_run, 'training_meta.json')\n",
                "    with open(meta_path, 'w', encoding='utf-8') as mf:\n",
                "        json.dump(meta_info, mf, indent=2)\n",
                "    print(f'✓ Metadata setting tersimpan di: {meta_path}')\n",
                "    \n",
                "    # 2. Kemas Arsip Evaluasi (.zip) untuk diunggah ke Raray Vision\n",
                f"    eval_zip_name = f'evaluasi_{model_key}_{{run_name}}_{{TANGGAL_TRAINING}}.zip'\n",
                "    eval_target_files = [\n",
                "        'results.csv', 'confusion_matrix.png', 'confusion_matrix_normalized.png',\n",
                "        'PR_curve.png', 'F1_curve.png', 'results.png', 'labels.jpg',\n",
                "        'val_batch0_pred.jpg', 'training_meta.json'\n",
                "    ]\n",
                "    with zipfile.ZipFile(eval_zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:\n",
                "        for ef in eval_target_files:\n",
                "            fp = os.path.join(latest_run, ef)\n",
                "            if os.path.exists(fp):\n",
                "                zf.write(fp, arcname=ef)\n",
                "                print(f'  + Arsip Eval: {ef}')\n",
                "    print(f'✓ File Evaluasi ZIP siap: {eval_zip_name} ({os.path.getsize(eval_zip_name)/1024:.1f} KB)')\n",
                "    \n",
                "    # 3. Identifikasi bobot best.pt dan best.onnx\n",
                "    best_pt_path = os.path.join(latest_run, 'weights', 'best.pt')\n",
                "    best_onnx_path = os.path.join(latest_run, 'weights', 'best.onnx')\n",
                "    if not os.path.exists(best_onnx_path):\n",
                "        pot_onnx = glob.glob(os.path.join(latest_run, '*.onnx'))\n",
                "        if pot_onnx:\n",
                "            best_onnx_path = pot_onnx[0]\n",
                "    \n",
                "    if os.path.exists(best_pt_path):\n",
                "        sz_pt = os.path.getsize(best_pt_path) / (1024 * 1024)\n",
                "        print(f'✓ File Bobot Model: {best_pt_path} ({sz_pt:.2f} MB)')\n",
                "    else:\n",
                "        print('⚠ File best.pt belum ditemukan di folder weights.')\n",
                "        \n",
                "    # 4. Buat All-In-One ZIP Bundle (Weights + Evaluasi)\n",
                f"    bundle_zip_name = f'raray_vision_{model_key}_{{run_name}}_{{TANGGAL_TRAINING}}_bundle.zip'\n",
                "    with zipfile.ZipFile(bundle_zip_name, 'w', zipfile.ZIP_DEFLATED) as bzf:\n",
                "        if os.path.exists(best_pt_path):\n",
                "            bzf.write(best_pt_path, arcname='best.pt')\n",
                "        if os.path.exists(best_onnx_path):\n",
                "            bzf.write(best_onnx_path, arcname='best.onnx')\n",
                "        for ef in eval_target_files:\n",
                "            fp = os.path.join(latest_run, ef)\n",
                "            if os.path.exists(fp):\n",
                "                bzf.write(fp, arcname=ef)\n",
                "    print(f'✓ File Bundle Lengkap ZIP: {bundle_zip_name} ({os.path.getsize(bundle_zip_name)/(1024*1024):.2f} MB)')\n"
            ]
        })

        # Download/Result Step (Langkah 10)
        if is_local:
            cells.append({
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"### 📁 Langkah 10: Lokasi Hasil Training\n",
                    "File hasil training tersimpan di folder lokal PC Anda. Siap untuk diunggah ke **Raray Vision**."
                ]
            })
            cells.append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# ==========================================================\n",
                    "# LOKASI FILE HASIL TRAINING (LOKAL PC)\n",
                    "# ==========================================================\n",
                    "import os\n",
                    "\n",
                    "print('🎉 TRAINING SELESAI!')\n",
                    "print('\\n📁 File hasil training tersimpan di:')\n",
                    "\n",
                    "if 'best_pt_path' in locals() and os.path.exists(best_pt_path):\n",
                    "    sz_pt = os.path.getsize(best_pt_path) / (1024 * 1024)\n",
                    "    print(f'  - Model Weights  : {os.path.abspath(best_pt_path)} ({sz_pt:.2f} MB)')\n",
                    "\n",
                    "if 'eval_zip_name' in locals() and os.path.exists(eval_zip_name):\n",
                    "    sz_zip = os.path.getsize(eval_zip_name) / 1024\n",
                    "    print(f'  - Arsip Evaluasi : {os.path.abspath(eval_zip_name)} ({sz_zip:.1f} KB)')\n",
                    "\n",
                    "if 'bundle_zip_name' in locals() and os.path.exists(bundle_zip_name):\n",
                    "    sz_bundle = os.path.getsize(bundle_zip_name) / (1024 * 1024)\n",
                    "    print(f'  - Bundle Lengkap : {os.path.abspath(bundle_zip_name)} ({sz_bundle:.2f} MB)')\n",
                    "\n",
                    "print('\\n📋 PANDUAN UNGGAH KE RARAY VISION:')\n",
                    "print('1. Buka web Raray Vision > Menu \"Model Management\".')\n",
                    "print('2. Klik tombol \"+ Upload Model (.pt / .onnx)\".')\n",
                    "print('3. Isi formulir:')\n",
                    "print('   - File Bobot Model (.pt): Pilih file best.pt dari path di atas.')\n",
                    "print(f'   - File Arsip Evaluasi (.zip): Pilih file evaluasi dari path di atas.')\n",
                    "print(f'   - Tanggal Training: {TANGGAL_TRAINING}')\n",
                    "print(f'   - Keterangan Setting: {KETERANGAN_SETTING}')\n",
                    "print('4. Klik \"Simpan Model\". Metrik mAP, Confusion Matrix, dan PR Curve akan langsung tampil!')\n",
                ]
            })
        else:
            cells.append({
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    f"### 📥 Langkah 10: Download Otomatis Bobot (`best.pt`) & Arsip Evaluasi ke Komputer\n",
                    "Menjalankan fungsi download Google Colab ke browser lokal Anda. Setelah terunduh, file siap diunggah ke web **Raray Vision** di menu **Model Management**."
                ]
            })
            cells.append({
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# ==========================================================\n",
                    "# DOWNLOAD LANGSUNG KE KOMPUTER ANDA\n",
                    "# ==========================================================\n",
                    "try:\n",
                    "    from google.colab import files\n",
                    "    print('📥 Memicu dialog pengunduhan browser...')\n",
                    "    \n",
                    "    if 'best_pt_path' in locals() and os.path.exists(best_pt_path):\n",
                    "        print(f'⬇️ Mengunduh model weights: best.pt ({os.path.getsize(best_pt_path)/(1024*1024):.2f} MB)...')\n",
                    "        files.download(best_pt_path)\n",
                    "    \n",
                    "    if 'eval_zip_name' in locals() and os.path.exists(eval_zip_name):\n",
                    "        print(f'⬇️ Mengunduh arsip evaluasi: {eval_zip_name}...')\n",
                    "        files.download(eval_zip_name)\n",
                    "        \n",
                    "    print('\\n🎉 Selesai! File sedang diunduh oleh browser Anda.')\n",
                    "    print('\\n📋 PANDUAN UNGGAH KE RARAY VISION:')\n",
                    "    print('1. Buka web Raray Vision > Menu \"Model Management\".')\n",
                    "    print('2. Klik tombol \"+ Upload Model (.pt / .onnx)\".')\n",
                    "    print('3. Isi formulir:')\n",
                    "    print('   - File Bobot Model (.pt): Pilih file best.pt yang baru diunduh.')\n",
                    "    print(f'   - File Arsip Evaluasi (.zip): Pilih file {eval_zip_name}.')\n",
                    "    print(f'   - Tanggal Training: {TANGGAL_TRAINING}')\n",
                    "    print(f'   - Keterangan Setting: {KETERANGAN_SETTING}')\n",
                    "    print('4. Klik \"Simpan Model\". Metrik mAP, Confusion Matrix, dan PR Curve akan langsung tampil!')\n",
                    "except ImportError:\n",
                    "    print('ℹ️ Script tidak dijalankan di Google Colab. File zip dan weights tersedia di direktori lokal.')\n",
                ]
            })
    else:
        # All models together — pass for now
        pass

    # Build notebook metadata (local mode uses standard kernelspec without Colab GPU accelerator)
    if is_local:
        nb_metadata = {
            "kernelspec": {
                "name": "python3",
                "display_name": "Python 3 (Lokal)"
            },
            "language_info": {
                "name": "python"
            }
        }
    else:
        nb_metadata = {
            "colab": {
                "provenance": [],
                "gpuType": "T4"
            },
            "kernelspec": {
                "name": "python3",
                "display_name": "Python 3"
            },
            "language_info": {
                "name": "python"
            },
            "accelerator": "GPU"
        }

    notebook_dict = {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": nb_metadata,
        "cells": cells
    }
    return notebook_dict



class DatasetUpdateRequest(BaseModel):
    name: str

class FeedbackRequest(BaseModel):
    feedback: str # backward-compatible: good, bad, pending
    notes: Optional[str] = None
    annotations: Optional[List["FeedbackAnnotation"]] = None
    image_width: Optional[int] = Field(None, gt=0)
    image_height: Optional[int] = Field(None, gt=0)
    source: Optional[str] = Field(None, max_length=80)
    source_record_id: Optional[str] = Field(None, max_length=160)
    actor_email: Optional[str] = Field(None, max_length=255)
    idempotency_key: Optional[str] = Field(None, max_length=255)

    @root_validator(skip_on_failure=True)
    def validate_annotation_bounds(cls, values):
        annotations = values.get("annotations") or []
        image_width, image_height = values.get("image_width"), values.get("image_height")
        if annotations and (image_width is None or image_height is None):
            raise ValueError("image_width and image_height are required with annotations")
        for ann in annotations:
            if ann.x + ann.width > image_width or ann.y + ann.height > image_height:
                raise ValueError("annotation rectangle must fit within image dimensions")
        return values


class FeedbackAnnotation(BaseModel):
    shape: str = "rectangle"
    label: str = Field(..., min_length=1, max_length=120)
    class_id: Optional[int] = Field(None, ge=0, le=32)
    x: float = Field(..., ge=0)
    y: float = Field(..., ge=0)
    width: float = Field(..., gt=0)
    height: float = Field(..., gt=0)

    @root_validator(skip_on_failure=True)
    def rectangle_only(cls, values):
        if values.get("shape") != "rectangle":
            raise ValueError("annotation shape must be rectangle")
        return values


if hasattr(FeedbackRequest, "model_rebuild"):
    FeedbackRequest.model_rebuild()
else:
    FeedbackRequest.update_forward_refs(FeedbackAnnotation=FeedbackAnnotation)

class LabelStudioSyncRequest(BaseModel):
    project_id: Optional[str] = None
    include_good: bool = True
    include_bad: bool = True
    model_id: Optional[int] = None
    endpoint_slug: Optional[str] = None

class ModelUpdateRequest(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    task_type: Optional[str] = None
    framework: Optional[str] = None
    description: Optional[str] = None

class EndpointCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    model_id: Optional[int] = None
    default_conf: float = 0.25
    default_iou: float = 0.45
    is_active: bool = True

class EndpointUpdateRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    model_id: Optional[int] = None
    default_conf: Optional[float] = None
    default_iou: Optional[float] = None
    is_active: Optional[bool] = None

class EndpointSwitchModelRequest(BaseModel):
    model_id: int



# ==========================================
# 1. Prediction & Feedback Endpoints
# ==========================================

@router.post("/predict")
async def predict_object(
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    conf_threshold: float = Form(0.25),
    iou_threshold: float = Form(0.45),
    db: Session = Depends(get_db)
):
    """
    Run object detection using the currently active model.
    Saves original and annotated images to S3, registers prediction in DB,
    and returns prediction_id with bounding boxes and annotated image URL.
    """
    if file:
        image_bytes = await file.read()
        filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}.jpg"
    elif image_url:
        import requests
        try:
            resp = requests.get(image_url, timeout=10)
            resp.raise_for_status()
            image_bytes = resp.content
            filename = os.path.basename(image_url.split("?")[0]) or "remote_image.jpg"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch image from URL: {e}")
    else:
        raise HTTPException(status_code=400, detail="Must provide an image file or image_url")

    # Run detection inference
    try:
        result = detection_service.predict(
            image_bytes,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")

    pred_id = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".jpg"

    # Upload original image to S3
    raw_s3_key = f"datasets/raw/{pred_id}{ext}"
    orig_url = s3_service.upload_bytes(image_bytes, raw_s3_key, content_type="image/jpeg")

    # Upload annotated visual image to S3
    annotated_s3_key = f"datasets/annotated/{pred_id}.jpg"
    annotated_url = s3_service.upload_bytes(result["annotated_bytes"], annotated_s3_key, content_type="image/jpeg")

    # Determine initial feedback status with 10% CV-Ops Human Audit Sampling
    import random
    initial_status = "pending"
    is_audit = False
    if result["top_confidence"] >= 0.88 and result["detection_count"] > 0:
        # 10% random sample for human verification in Label Studio to prevent confirmation bias
        if random.random() < 0.10:
            initial_status = "audit_required"
            is_audit = True
        else:
            initial_status = "auto_labeled"

    # Store prediction record in DB
    pred_record = MLPrediction(
        id=pred_id,
        model_id=result["model_id"],
        model_version=result["model_version"],
        original_image_url=orig_url,
        annotated_image_url=annotated_url,
        detections=json.dumps(result["detections"]),
        top_confidence=result["top_confidence"],
        detection_count=result["detection_count"],
        latency_ms=result["latency_ms"],
        feedback_status=initial_status,
        is_audit_sample=is_audit,
        image_quality=json.dumps(result.get("quality", {})),
        image_width=result.get("image_width"),
        image_height=result.get("image_height"),
        is_synced_to_ls=False
    )
    db.add(pred_record)
    db.commit()

    return {
        "prediction_id": pred_id,
        "model_id": result["model_id"],
        "model_name": result["model_name"],
        "model_version": result["model_version"],
        "original_image_url": orig_url,
        "annotated_image_url": annotated_url,
        "detections": result["detections"],
        "detection_count": result["detection_count"],
        "top_confidence": result["top_confidence"],
        "latency_ms": result["latency_ms"],
        "image_width": result["image_width"],
        "image_height": result["image_height"],
        "quality": result.get("quality", {}),
        "feedback_status": initial_status,
        "is_audit_sample": is_audit
    }


@router.post("/feedback/{prediction_id}")
async def submit_feedback(
    prediction_id: str,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    idempotency_header: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Submit user feedback on a prediction:
    'good' -> Accurate prediction, verified for auto-labeling.
    'bad' -> Inaccurate prediction, flagged for Label Studio human review queue.
    """
    record = db.query(MLPrediction).filter(MLPrediction.id == prediction_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Prediction record not found")

    # When the prediction model publishes the canonical 33-class vocabulary,
    # reject typo/foreign labels while retaining compatibility with older model
    # rows that did not persist a class list.
    if payload.annotations and record.model_id:
        model = db.query(MLModel).filter(MLModel.id == record.model_id).first()
        model_classes = json.loads(model.classes or "[]") if model and model.classes else []
        if len(model_classes) == 33:
            canonical = {str(name).strip().casefold(): index for index, name in enumerate(model_classes)}
            for annotation in payload.annotations:
                label_key = annotation.label.strip().casefold()
                if label_key not in canonical:
                    raise HTTPException(status_code=422, detail=f"Unknown canonical tire class: {annotation.label}")
                if annotation.class_id is not None and annotation.class_id != canonical[label_key]:
                    raise HTTPException(status_code=422, detail="annotation class_id does not match label")

    idempotency_key = payload.idempotency_key or idempotency_header
    if idempotency_key:
        previous = db.query(MLPrediction).filter(
            MLPrediction.id == prediction_id,
            MLPrediction.feedback_idempotency_key == idempotency_key,
        ).first()
        if previous:
            return {
                "success": True,
                "prediction_id": previous.id,
                "feedback_status": previous.feedback_status,
                "feedback_notes": previous.feedback_notes,
                "corrected_annotations": json.loads(previous.corrected_annotations or "[]"),
                "idempotent_replay": True,
            }
        if record.feedback_idempotency_key and record.feedback_idempotency_key != idempotency_key:
            raise HTTPException(status_code=409, detail="Feedback untuk prediksi ini sudah tercatat.")

    status_val = payload.feedback.lower().strip()
    if status_val not in ["good", "bad", "pending"]:
        raise HTTPException(status_code=400, detail="Feedback must be 'good', 'bad', or 'pending'")

    record.feedback_status = status_val
    if payload.notes:
        record.feedback_notes = payload.notes
    if payload.annotations is not None:
        record.corrected_annotations = json.dumps([a.dict() for a in payload.annotations])
        record.image_width = payload.image_width
        record.image_height = payload.image_height
    record.feedback_source = payload.source or "HERO"
    if payload.source_record_id is not None:
        record.feedback_source_record_id = payload.source_record_id
    record.feedback_actor_id = getattr(current_user, "id", None)
    current_actor_email = getattr(current_user, "email", None)
    trusted_service_email = (
        os.getenv("HERO_SERVICE_EMAIL") or os.getenv("RARAY_VISION_EMAIL") or ""
    ).strip().casefold()
    delegated_actor_email = payload.actor_email if (
        payload.source == "HERO"
        and trusted_service_email
        and str(current_actor_email or "").strip().casefold() == trusted_service_email
    ) else None
    record.feedback_actor_email = delegated_actor_email or current_actor_email
    record.feedback_idempotency_key = idempotency_key
    record.feedback_updated_at = datetime.utcnow()
    record.is_synced_to_ls = False # Reset sync flag so it gets picked up in next sync

    db.commit()
    db.refresh(record)

    return {
        "success": True,
        "prediction_id": record.id,
        "feedback_status": record.feedback_status,
        "feedback_notes": record.feedback_notes,
        "corrected_annotations": json.loads(record.corrected_annotations or "[]"),
        "idempotency_replay": False,
        "message": f"Feedback '{record.feedback_status}' successfully recorded."
    }


# ==========================================
# 2. Model Management & Versioning Endpoints
# ==========================================

@router.get("")
def list_models(db: Session = Depends(get_db)):
    """List all registered models with their active status, metrics, and download flags."""
    models = db.query(MLModel).order_by(MLModel.created_at.desc()).all()
    results = []
    for m in models:
        metrics = json.loads(m.metrics_summary) if m.metrics_summary else {}
        classes = json.loads(m.classes) if m.classes else []
        eval_dir = m.evaluation_dir or os.path.join(detection_service.evaluations_dir, f"model_{m.id}")
        has_eval = bool(os.path.exists(eval_dir) and os.listdir(eval_dir))
        has_w = bool(m.model_path and os.path.exists(m.model_path))
        has_o = bool(m.onnx_path and os.path.exists(m.onnx_path))
        results.append({
            "id": m.id,
            "name": m.name,
            "version": m.version,
            "task_type": m.task_type,
            "framework": m.framework,
            "is_active": m.is_active,
            "description": m.description,
            "classes": classes,
            "classes_count": len(classes),
            "metrics": metrics,
            "has_weights": has_w,
            "has_evaluation": has_eval,
            "has_onnx": has_o,
            "created_at": m.created_at.isoformat() if m.created_at else None
        })
    return {"models": results}


@router.post("/upload")
async def upload_model(
    name: str = Form(...),
    version: str = Form(...),
    task_type: str = Form("detection"),
    framework: str = Form("yolo"),
    description: Optional[str] = Form(None),
    training_date: Optional[str] = Form(None),
    training_settings: Optional[str] = Form(None),
    model_file: UploadFile = File(...),
    onnx_file: Optional[UploadFile] = File(None),
    results_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    Upload a trained model (.pt or .onnx) and optional evaluation results zip.
    Extracts metrics, stores training settings & date, and creates registry entry.
    """
    # Ensure model file extension
    m_ext = os.path.splitext(model_file.filename)[1].lower()
    if m_ext not in [".pt", ".onnx"]:
        raise HTTPException(status_code=400, detail="Model file must be .pt or .onnx")

    # Save model weights file (.pt or .onnx)
    safe_name = f"{name.replace(' ', '_').lower()}_{version.replace(' ', '_').lower()}_{uuid.uuid4().hex[:6]}{m_ext}"
    model_dest = os.path.join(detection_service.models_storage_dir, safe_name)
    with open(model_dest, "wb") as f:
        f.write(await model_file.read())

    # Save accompanying .onnx file if provided
    onnx_dest = None
    if onnx_file:
        o_name = f"{name.replace(' ', '_').lower()}_{version.replace(' ', '_').lower()}_{uuid.uuid4().hex[:6]}.onnx"
        onnx_dest = os.path.join(detection_service.models_storage_dir, o_name)
        with open(onnx_dest, "wb") as f:
            f.write(await onnx_file.read())

    # Try reading classes from YOLO model if .pt
    classes_list = []
    try:
        from ultralytics import YOLO
        y_temp = YOLO(model_dest)
        if hasattr(y_temp, "names") and y_temp.names:
            classes_list = list(y_temp.names.values())
    except Exception as e:
        print(f"[ModelUpload] Note: could not extract classes automatically: {e}")

    # Build initial metrics dict with date & settings if provided
    initial_metrics = {}
    if training_date and training_date.strip():
        initial_metrics["training_date"] = training_date.strip()
    if training_settings and training_settings.strip():
        initial_metrics["training_settings"] = training_settings.strip()

    # Create DB entry first to get ID
    new_model = MLModel(
        name=name,
        version=version,
        task_type=task_type,
        framework=framework,
        model_path=model_dest,
        onnx_path=onnx_dest,
        classes=json.dumps(classes_list),
        is_active=False,
        description=description,
        metrics_summary=json.dumps(initial_metrics)
    )
    db.add(new_model)
    db.commit()
    db.refresh(new_model)

    # Process evaluation archive if provided
    eval_metrics = dict(initial_metrics)
    if results_file:
        zip_temp_path = os.path.join(detection_service.evaluations_dir, f"temp_{new_model.id}.zip")
        with open(zip_temp_path, "wb") as f:
            f.write(await results_file.read())
        
        try:
            eval_result = detection_service.process_evaluation_archive(zip_temp_path, new_model.id)
            for k, v in eval_result["metrics"].items():
                eval_metrics[k] = v
            # Ensure form inputs take precedence if provided
            if training_date and training_date.strip():
                eval_metrics["training_date"] = training_date.strip()
            if training_settings and training_settings.strip():
                eval_metrics["training_settings"] = training_settings.strip()

            if not new_model.description and eval_metrics.get("training_settings"):
                new_model.description = str(eval_metrics["training_settings"])

            new_model.metrics_summary = json.dumps(eval_metrics)
            new_model.evaluation_dir = eval_result["evaluation_dir"]
            db.commit()
        except Exception as e:
            print(f"[ModelUpload] Error processing results zip: {e}")
        finally:
            if os.path.exists(zip_temp_path):
                os.remove(zip_temp_path)

    return {
        "success": True,
        "message": f"Model '{name}' ({version}) berhasil diunggah.",
        "model": {
            "id": new_model.id,
            "name": new_model.name,
            "version": new_model.version,
            "classes": classes_list,
            "metrics": eval_metrics
        }
    }


@router.post("/rollback")
def rollback_model(db: Session = Depends(get_db)):
    """Instant 1-Click Rollback to previous active model in production."""
    result = detection_service.rollback_model(db)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/{model_id}/export-onnx")
def export_model_to_onnx(model_id: int, db: Session = Depends(get_db)):
    """Export a PyTorch .pt model to ONNX runtime format for CPU acceleration."""
    result = detection_service.export_to_onnx(model_id, db)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result

@router.put("/{model_id}/activate")
def activate_model(model_id: int, db: Session = Depends(get_db)):
    """Hot-swap the active inference model without restarting the server."""
    result = detection_service.hot_swap_model(model_id, db)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.put("/{model_id}")
def update_model(model_id: int, payload: ModelUpdateRequest, db: Session = Depends(get_db)):
    """Update model metadata (name, version, framework, description, task_type)."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if payload.name is not None and payload.name.strip():
        model.name = payload.name.strip()
    if payload.version is not None and payload.version.strip():
        model.version = payload.version.strip()
    if payload.task_type is not None and payload.task_type.strip():
        model.task_type = payload.task_type.strip()
    if payload.framework is not None and payload.framework.strip():
        model.framework = payload.framework.strip()
    if payload.description is not None:
        model.description = payload.description.strip()

    db.commit()
    db.refresh(model)

    detection_service.invalidate_model_cache(model_id)

    return {
        "success": True,
        "message": f"Model '{model.name}' berhasil diperbarui.",
        "model": {
            "id": model.id,
            "name": model.name,
            "version": model.version,
            "task_type": model.task_type,
            "framework": model.framework,
            "description": model.description
        }
    }


@router.delete("/{model_id}")
def delete_model(model_id: int, force: bool = False, db: Session = Depends(get_db)):
    """Delete a model from registry, unlink from endpoints, and clean filesystem."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    # If it is active, check if there are other models available to auto-activate
    if model.is_active:
        other_model = db.query(MLModel).filter(MLModel.id != model_id).first()
        if other_model:
            detection_service.hot_swap_model(other_model.id, db)
        elif not force:
            raise HTTPException(
                status_code=400,
                detail="Model ini adalah satu-satunya model aktif di sistem. Harap unggah model pengganti sebelum menghapus."
            )

    # Decouple endpoints referencing this model
    endpoints_using = db.query(MLEndpoint).filter(MLEndpoint.model_id == model_id).all()
    for ep in endpoints_using:
        ep.model_id = None
    if endpoints_using:
        db.commit()

    # Invalidate memory cache
    detection_service.invalidate_model_cache(model_id)

    # Remove files safely
    try:
        if model.model_path and os.path.exists(model.model_path):
            os.remove(model.model_path)
        if model.onnx_path and os.path.exists(model.onnx_path):
            os.remove(model.onnx_path)
        if model.evaluation_dir and os.path.exists(model.evaluation_dir):
            shutil.rmtree(model.evaluation_dir, ignore_errors=True)
    except Exception as e:
        print(f"[DeleteModel] File removal error: {e}")

    db.delete(model)
    db.commit()
    return {
        "success": True, 
        "message": f"Model '{model.name} ({model.version})' berhasil dihapus.",
        "unlinked_endpoints": len(endpoints_using)
    }


@router.get("/{model_id}/evaluation")
def get_model_evaluation(model_id: int, db: Session = Depends(get_db)):
    """Get offline training evaluation assets and metrics for a model."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    metrics = json.loads(model.metrics_summary) if model.metrics_summary else {}
    visuals = {}

    eval_dir = model.evaluation_dir or os.path.join(detection_service.evaluations_dir, f"model_{model_id}")
    has_eval = False
    if os.path.exists(eval_dir) and os.listdir(eval_dir):
        has_eval = True
        eval_keys = [
            ("confusion_matrix", "confusion_matrix.png"),
            ("confusion_matrix_norm", "confusion_matrix_normalized.png"),
            ("pr_curve", "PR_curve.png"),
            ("f1_curve", "F1_curve.png"),
            ("results_png", "results.png"),
            ("labels", "labels.jpg"),
            ("val_pred", "val_batch0_pred.jpg")
        ]
        for key, fname in eval_keys:
            if os.path.exists(os.path.join(eval_dir, fname)):
                visuals[key] = f"/uploads/evaluations/model_{model_id}/{fname}"

    return {
        "model_id": model.id,
        "name": model.name,
        "version": model.version,
        "framework": model.framework,
        "description": model.description,
        "created_at": model.created_at.isoformat() if model.created_at else None,
        "has_weights": bool(model.model_path and os.path.exists(model.model_path)),
        "has_onnx": bool(model.onnx_path and os.path.exists(model.onnx_path)),
        "has_evaluation": has_eval,
        "metrics": metrics,
        "visuals": visuals
    }


@router.get("/{model_id}/download-weights")
def download_model_weights(model_id: int, db: Session = Depends(get_db)):
    """Download the trained model weights file (.pt or .onnx)."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if not model.model_path or not os.path.exists(model.model_path):
        raise HTTPException(status_code=404, detail="File bobot model tidak ditemukan di disk.")

    ext = os.path.splitext(model.model_path)[1]
    safe_name = f"{model.name.replace(' ', '_').lower()}_{model.version.replace(' ', '_').lower()}_best{ext}"
    return FileResponse(
        path=model.model_path,
        filename=safe_name,
        media_type="application/octet-stream"
    )


@router.get("/{model_id}/download-onnx")
def download_model_onnx(model_id: int, db: Session = Depends(get_db)):
    """Download the ONNX model file for CPU serving."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if not model.onnx_path or not os.path.exists(model.onnx_path):
        raise HTTPException(status_code=404, detail="File ONNX model tidak ditemukan di disk.")

    safe_name = f"{model.name.replace(' ', '_').lower()}_{model.version.replace(' ', '_').lower()}_best.onnx"
    return FileResponse(
        path=model.onnx_path,
        filename=safe_name,
        media_type="application/octet-stream"
    )


@router.get("/{model_id}/download-evaluation")
def download_model_evaluation(model_id: int, db: Session = Depends(get_db)):
    """Package and download the evaluation directory as a zip archive."""
    model = db.query(MLModel).filter(MLModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    eval_dir = model.evaluation_dir or os.path.join(detection_service.evaluations_dir, f"model_{model_id}")
    if not os.path.exists(eval_dir) or not os.listdir(eval_dir):
        raise HTTPException(status_code=404, detail="Arsip hasil evaluasi tidak ditemukan untuk model ini.")

    # Create zip archive in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(eval_dir):
            for f in files:
                full_p = os.path.join(root, f)
                rel_p = os.path.relpath(full_p, eval_dir)
                zf.write(full_p, arcname=rel_p)

    zip_buffer.seek(0)
    safe_name = f"{model.name.replace(' ', '_').lower()}_{model.version.replace(' ', '_').lower()}_evaluasi.zip"
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'}
    )


# ==========================================
# 3. Production Analytics & Feedback Dashboard
# ==========================================

@router.get("/analytics/production")
def get_production_analytics(
    model_id: Optional[int] = Query(None),
    endpoint_slug: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get online production statistics filtered by model or endpoint."""
    base_q = db.query(MLPrediction)
    if model_id is not None:
        base_q = base_q.filter(MLPrediction.model_id == model_id)
    if endpoint_slug is not None and endpoint_slug.strip():
        base_q = base_q.filter(MLPrediction.endpoint_slug == endpoint_slug.strip())

    total_preds = base_q.count()
    good_count = base_q.filter(MLPrediction.feedback_status == "good").count()
    bad_count = base_q.filter(MLPrediction.feedback_status == "bad").count()
    auto_count = base_q.filter(MLPrediction.feedback_status == "auto_labeled").count()
    audit_count = base_q.filter(MLPrediction.feedback_status == "audit_required").count()
    pending_count = base_q.filter(MLPrediction.feedback_status == "pending").count()

    unsynced_review_count = base_q.filter(
        MLPrediction.feedback_status == "bad",
        MLPrediction.is_synced_to_ls == False
    ).count()

    unsynced_auto_count = base_q.filter(
        MLPrediction.feedback_status.in_(["good", "auto_labeled"]),
        MLPrediction.is_synced_to_ls == False
    ).count()

    from sqlalchemy import func
    avg_lat = base_q.with_entities(func.avg(MLPrediction.latency_ms)).scalar() or 0.0

    recent_preds = base_q.order_by(MLPrediction.created_at.desc()).limit(12).all()
    recent_items = []
    for p in recent_preds:
        recent_items.append({
            "id": p.id,
            "model_id": p.model_id,
            "model_version": p.model_version,
            "endpoint_slug": p.endpoint_slug or "default",
            "original_image_url": p.original_image_url,
            "annotated_image_url": p.annotated_image_url,
            "detection_count": p.detection_count,
            "top_confidence": p.top_confidence,
            "latency_ms": p.latency_ms,
            "feedback_status": p.feedback_status,
            "is_audit_sample": p.is_audit_sample,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })

    return {
        "total_predictions": total_preds,
        "feedback": {
            "good": good_count,
            "bad": bad_count,
            "auto_labeled": auto_count,
            "audit_required": audit_count,
            "pending": pending_count,
            "accuracy_ratio": round((good_count + auto_count) / total_preds * 100, 1) if total_preds > 0 else 100.0
        },
        "review_queue": {
            "pending_human_review": bad_count,
            "unsynced_to_label_studio": unsynced_review_count,
            "unsynced_auto_labeled": unsynced_auto_count
        },
        "performance": {
            "avg_latency_ms": round(avg_lat, 1),
            "active_model": {
                "id": detection_service.active_model_id,
                "name": detection_service.active_model_name,
                "version": detection_service.active_model_version,
                "classes_count": len(detection_service.active_classes)
            }
        },
        "recent_predictions": recent_items,
        "filter": {
            "model_id": model_id,
            "endpoint_slug": endpoint_slug
        }
    }


# ==========================================
# 4. Data Sync to Label Studio & CVAT Import
# ==========================================

@router.post("/data/sync-label-studio")
def sync_to_label_studio(
    payload: LabelStudioSyncRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Push queued images (flagged 'bad' or 'good'/'auto_labeled') directly to Label Studio
    via its REST API for the monthly or periodic labeling cycle.
    """
    statuses_to_sync = []
    if payload.include_bad:
        statuses_to_sync.append("bad")
    if payload.include_good:
        statuses_to_sync.extend(["good", "auto_labeled"])

    sync_q = db.query(MLPrediction).filter(
        MLPrediction.feedback_status.in_(statuses_to_sync),
        MLPrediction.is_synced_to_ls == False
    )
    if payload.model_id:
        sync_q = sync_q.filter(MLPrediction.model_id == payload.model_id)
    if payload.endpoint_slug:
        sync_q = sync_q.filter(MLPrediction.endpoint_slug == payload.endpoint_slug)
    items = sync_q.limit(200).all()

    if not items:
        return {"success": True, "synced_count": 0, "message": "No pending items to sync."}

    tasks = []
    record_map = {}

    for item in items:
        detections = json.loads(item.detections) if item.detections else []
        corrected = json.loads(item.corrected_annotations) if item.corrected_annotations else []
        # Human rectangles are authoritative training annotations; thumbs are
        # routing metadata only and never replace the corrected geometry.
        annotation_source = corrected or detections
        task_data = {
            "data": {
                "image": item.original_image_url,
                "prediction_id": item.id,
                "feedback_status": item.feedback_status,
                "feedback_notes": item.feedback_notes or "",
                "feedback_source": item.feedback_source or "HERO",
                "feedback_source_record_id": item.feedback_source_record_id or "",
            }
        }

        # Corrected annotations are sent for either good/bad feedback. Legacy
        # predictions retain the previous good/auto_labeled behavior.
        if annotation_source and (corrected or item.feedback_status in ["good", "auto_labeled"]):
            ls_results = label_studio_service.format_detection_to_ls_annotation(
                annotation_source,
                img_width=item.image_width or 1000,
                img_height=item.image_height or 1000,
            )
            task_data["predictions"] = [
                {
                    "model_version": item.model_version or "active",
                    "result": ls_results
                }
            ]

        tasks.append(task_data)
        record_map[item.id] = item

    # Push to Label Studio
    result = label_studio_service.push_bulk_tasks(tasks, project_id=payload.project_id)

    if result.get("success"):
        # Mark as synced in DB
        response_tasks = result.get("response")
        if isinstance(response_tasks, dict):
            response_tasks = response_tasks.get("tasks") or response_tasks.get("items") or []
        if not isinstance(response_tasks, list):
            response_tasks = []
        task_ids = []
        for task in response_tasks:
            raw_task_id = task.get("id") if isinstance(task, dict) else None
            if isinstance(raw_task_id, bool) or not str(raw_task_id or "").isdigit():
                task_ids = []
                break
            task_ids.append(int(raw_task_id))
        if len(task_ids) != len(items):
            for item in items:
                item.feedback_status = "sync_reconciliation_required"
                item.feedback_notes = (
                    "Label Studio menerima import tetapi mapping task ID tidak lengkap; "
                    "rekonsiliasi manual diperlukan. "
                    f"{item.feedback_notes or ''}"
                )[:4000]
            db.commit()
            return {
                "success": False,
                "error": "Label Studio tidak mengembalikan mapping task lengkap; status dipindah ke rekonsiliasi.",
                "synced_count": 0,
            }
        for index, item in enumerate(items):
            item.is_synced_to_ls = True
            item.label_studio_task_id = task_ids[index]
        db.commit()

        return {
            "success": True,
            "synced_count": len(items),
            "message": f"Successfully pushed {len(items)} tasks to Label Studio."
        }
    else:
        return {
            "success": False,
            "error": result.get("error"),
            "message": "Failed to push to Label Studio. Ensure Label Studio is running and API token is valid."
        }


async def import_cvat_dataset(
    dataset_name: Optional[str] = Form(None),
    coco_json_file: UploadFile = File(...),
    images_zip_file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    job_id: Optional[str] = None,
):
    """
    Import CVAT COCO dataset:
    1. Creates a dedicated folder in S3: datasets/{dataset_folder}/images/
    2. Uploads all images into that dedicated S3 folder
    3. Converts COCO bounding boxes into Label Studio tasks.json
    4. Saves label_studio_tasks.json in the S3 folder
    5. Returns S3 URI, Folder Prefix, Bucket, and Tasks URL ready to COPY directly into Label Studio!
    """
    from datetime import datetime
    import re
    from backend.app.services.s3_service import get_s3_credentials

    # Sanitize dataset name
    raw_name = dataset_name or "cvat_dataset"
    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_name).strip('_').lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{slug}_{timestamp}"
    s3_folder_prefix = f"datasets/{folder_name}/images"

    coco_content = await coco_json_file.read()
    try:
        coco_json = json.loads(coco_content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid COCO JSON file: {e}")

    import tempfile
    import concurrent.futures

    # Stream multi-GB zip to disk in 8MB chunks to prevent memory explosion & timeouts
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = temp_zip.name

    try:
        while chunk := await images_zip_file.read(1024 * 1024 * 8):
            temp_zip.write(chunk)
        temp_zip.close()

        image_url_mapping = {}
        uploaded_files = []

        endpoint, bucket, _, region, _, _ = get_s3_credentials()

        with zipfile.ZipFile(temp_zip_path, "r") as zf:
            valid_members = [
                m for m in zf.namelist()
                if os.path.basename(m) and not m.endswith("/") and not m.startswith("__MACOSX")
            ]
            if job_id:
                with _dataset_jobs_lock:
                    _dataset_jobs[job_id].update(
                        stage="extracting", percentage=10,
                        message=f"ZIP terbaca: {len(valid_members)} file. Mengekstrak dan mengunggah gambar..."
                    )

            def upload_single_member(member_name):
                fname = os.path.basename(member_name)
                f_bytes = zf.read(member_name)
                s3_key = f"{s3_folder_prefix}/{fname}"
                ext = os.path.splitext(fname)[1].lower()
                c_type = "image/jpeg"
                if ext == ".png":
                    c_type = "image/png"
                elif ext == ".webp":
                    c_type = "image/webp"
                url = s3_service.upload_bytes(f_bytes, s3_key, content_type=c_type)
                return fname, url

            # Upload images concurrently with 12 threads for 5-10x speedup
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
                future_to_member = {executor.submit(upload_single_member, m): m for m in valid_members}
                total_members = max(len(valid_members), 1)
                for completed, future in enumerate(concurrent.futures.as_completed(future_to_member), start=1):
                    try:
                        fname, accessible_url = future.result()
                        if accessible_url:
                            image_url_mapping[fname] = _stable_dataset_url(accessible_url)
                            uploaded_files.append(fname)
                    except Exception as err:
                        print(f"[CVATImport] Error uploading {future_to_member[future]}: {err}")
                    if job_id and (completed == total_members or completed % max(total_members // 100, 1) == 0):
                        with _dataset_jobs_lock:
                            _dataset_jobs[job_id].update(
                                stage="uploading", percentage=min(95, 10 + round(completed / total_members * 85)),
                                message=f"Ekstraksi & upload storage: {completed}/{len(valid_members)} gambar."
                            )

        # Convert COCO annotations to Label Studio format
        tasks = label_studio_service.convert_coco_to_label_studio(coco_json, image_url_mapping)
        for task in tasks:
            if isinstance(task, dict) and isinstance(task.get("data"), dict):
                task["data"]["image"] = _dataset_image_url(
                    task["data"].get("image", ""), folder_name, image_url_mapping,
                    task["data"].get("original_filename"),
                )

        # Also save tasks.json in S3 folder for direct import in Label Studio
        tasks_json_bytes = json.dumps(tasks, indent=2).encode("utf-8")
        tasks_s3_key = f"datasets/{folder_name}/label_studio_tasks.json"
        tasks_url = _stable_dataset_url(s3_service.upload_bytes(tasks_json_bytes, tasks_s3_key, content_type="application/json"))

        # Save COCO annotations (with S3 image URLs embedded) for RF-DETR & PyTorch COCO Evaluators
        coco_annotations_s3_key = f"datasets/{folder_name}/annotations_coco.json"
        coco_s3_bytes = json.dumps(coco_json, indent=2).encode("utf-8")
        coco_url = _stable_dataset_url(s3_service.upload_bytes(coco_s3_bytes, coco_annotations_s3_key, content_type="application/json"))

        # Generate YOLO data.yaml configuration file
        import yaml
        cat_list = coco_json.get("categories", [])
        if cat_list:
            sorted_cats = sorted(cat_list, key=lambda x: x.get("id", 0))
            yolo_names = {i: c.get("name") or f"class_{i}" for i, c in enumerate(sorted_cats)}
            cat_names = list(yolo_names.values())
        else:
            cat_names = ["object"]
            yolo_names = {0: "object"}

        yolo_yaml_data = {
            "path": "/content/dataset",
            "train": "images/train",
            "val": "images/val",
            "nc": len(cat_names),
            "names": yolo_names
        }
        yolo_yaml_bytes = yaml.dump(yolo_yaml_data, sort_keys=False).encode("utf-8")
        yolo_yaml_s3_key = f"datasets/{folder_name}/data.yaml"
        yolo_yaml_url = _stable_dataset_url(s3_service.upload_bytes(yolo_yaml_bytes, yolo_yaml_s3_key, content_type="text/yaml"))

        # Optionally push directly if Label Studio instance is configured
        ls_push_result = None
        if project_id:
            ls_push_result = label_studio_service.push_bulk_tasks(tasks, project_id=project_id)

        s3_uri = f"s3://{bucket}/{s3_folder_prefix}/"

        # Build Interactive .ipynb Notebooks per Model (YOLO-X, YOLO-26, RF-DETR)
        colab_yolox_dict = generate_colab_notebook_dict(folder_name, yolo_yaml_url, tasks_url, coco_url, model_type="yolox")
        colab_yolox_bytes = json.dumps(colab_yolox_dict, indent=2).encode("utf-8")
        colab_yolox_url = _stable_dataset_url(s3_service.upload_bytes(colab_yolox_bytes, f"datasets/{folder_name}/raray_vision_yolox_colab.ipynb", content_type="application/x-ipynb+json"))

        colab_yolo26_dict = generate_colab_notebook_dict(folder_name, yolo_yaml_url, tasks_url, coco_url, model_type="yolo26")
        colab_yolo26_bytes = json.dumps(colab_yolo26_dict, indent=2).encode("utf-8")
        colab_yolo26_url = _stable_dataset_url(s3_service.upload_bytes(colab_yolo26_bytes, f"datasets/{folder_name}/raray_vision_yolo26_colab.ipynb", content_type="application/x-ipynb+json"))

        colab_rfdetr_dict = generate_colab_notebook_dict(folder_name, yolo_yaml_url, tasks_url, coco_url, model_type="rfdetr")
        colab_rfdetr_bytes = json.dumps(colab_rfdetr_dict, indent=2).encode("utf-8")
        colab_rfdetr_url = _stable_dataset_url(s3_service.upload_bytes(colab_rfdetr_bytes, f"datasets/{folder_name}/raray_vision_rfdetr_colab.ipynb", content_type="application/x-ipynb+json"))

        colab_all_dict = generate_colab_notebook_dict(folder_name, yolo_yaml_url, tasks_url, coco_url, model_type="all")
        colab_all_bytes = json.dumps(colab_all_dict, indent=2).encode("utf-8")
        colab_nb_url = _stable_dataset_url(s3_service.upload_bytes(colab_all_bytes, f"datasets/{folder_name}/raray_vision_colab_training.ipynb", content_type="application/x-ipynb+json"))

        # Ready-to-run Colab code snippets
        snippets = build_colab_snippets(
            folder_name=folder_name,
            yolo_yaml_url=yolo_yaml_url,
            tasks_url=tasks_url,
            coco_url=coco_url
        )
        colab_yolo_snippet = snippets["yolo_code"]
        colab_yolo26_snippet = snippets["yolo26_code"]
        colab_rfdetr_snippet = snippets["rfdetr_code"]

        return {
            "success": True,
            "dataset_folder": folder_name,
            "s3_bucket": bucket,
            "s3_folder_prefix": f"{s3_folder_prefix}/",
            "s3_uri": s3_uri,
            "s3_endpoint": endpoint,
            "tasks_json_url": tasks_url,
            "coco_json_url": coco_url,
            "yolo_yaml_url": yolo_yaml_url,
            "colab_notebook_url": colab_nb_url,
            "images_uploaded_count": len(uploaded_files),
            "tasks_created_count": len(tasks),
            "categories": cat_names,
            "images": [
                {"name": name, "url": image_url_mapping[name]}
                for name in sorted(image_url_mapping)
            ],
            "colab_training": {
                "notebook_url": colab_nb_url,
                "data_yaml_url": yolo_yaml_url,
                "coco_json_url": coco_url,
                "yolo_code": colab_yolo_snippet,
                "yolo26_code": colab_yolo26_snippet,
                "rfdetr_code": colab_rfdetr_snippet
            },
            "label_studio_instructions": {
                "method_1_cloud_storage": {
                    "storage_type": "AWS S3",
                    "bucket_name": bucket,
                    "bucket_prefix": f"{s3_folder_prefix}/",
                    "s3_endpoint": endpoint,
                    "use_pre_signed_urls": True
                },
                "method_2_direct_import_url": tasks_url
            },
            "message": f"Dataset berhasil diunggah ke folder S3 '{folder_name}'. URL untuk Label Studio, file .ipynb Colab, YOLO-X, YOLO-26, dan RF-DETR siap digunakan."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengimpor dataset: {str(e)}")
    finally:
        if os.path.exists(temp_zip_path):
            try:
                os.remove(temp_zip_path)
            except Exception:
                pass


def _run_dataset_import(job_id: str, name: str, coco_path: str, zip_path: str, project_id: Optional[str]):
    """Process a staged upload after the HTTP upload request has completed."""
    from starlette.datastructures import UploadFile as StarletteUploadFile

    with _dataset_jobs_lock:
        _dataset_jobs[job_id].update(
            status="processing", stage="extracting", percentage=5,
            message="Upload selesai. ZIP sedang diekstrak dan gambar sedang dikirim ke storage."
        )
    try:
        with open(coco_path, "rb") as coco_handle, open(zip_path, "rb") as zip_handle:
            result = asyncio.run(import_cvat_dataset(
                dataset_name=name,
                coco_json_file=StarletteUploadFile(coco_handle, filename="annotations.json"),
                images_zip_file=StarletteUploadFile(zip_handle, filename="images.zip"),
                project_id=project_id,
                job_id=job_id,
            ))

        dataset_id = str(uuid.uuid4())
        result["label_studio_import_url"] = _dataset_import_url(dataset_id)
        result["label_studio_instructions"]["method_2_direct_import_url"] = result["label_studio_import_url"]
        artifacts = {key: result.get(key) for key in (
            "s3_bucket", "s3_folder_prefix", "s3_uri", "s3_endpoint", "tasks_json_url",
            "coco_json_url", "yolo_yaml_url", "colab_notebook_url", "colab_training",
            "label_studio_instructions", "label_studio_import_url"
        )}
        db = SessionLocal()
        try:
            dataset = MLDataset(
                id=dataset_id, name=name, folder=result["dataset_folder"], status="ready",
                image_count=result["images_uploaded_count"], task_count=result["tasks_created_count"],
                categories=json.dumps(result.get("categories", [])),
                images=json.dumps(result.get("images", [])), artifacts=json.dumps(artifacts),
            )
            db.add(dataset)
            db.commit()
        finally:
            db.close()

        result["id"] = dataset_id
        result["name"] = name
        with _dataset_jobs_lock:
            _dataset_jobs[job_id].update(
                status="completed", stage="ready", percentage=100,
                message="Dataset siap digunakan.", result=result
            )
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        with _dataset_jobs_lock:
            _dataset_jobs[job_id].update(
                status="failed", stage="failed", message=f"Pemrosesan gagal: {detail}", error=str(detail)
            )
    finally:
        for path in (coco_path, zip_path):
            try:
                os.remove(path)
            except OSError:
                pass


@router.post("/data/import-cvat", status_code=202)
async def start_cvat_dataset_import(
    background_tasks: BackgroundTasks,
    dataset_name: Optional[str] = Form(None),
    coco_json_file: UploadFile = File(...),
    images_zip_file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
):
    """Stage large files on disk and return a job immediately after upload."""
    job_id = str(uuid.uuid4())
    staging_dir = os.path.join(BASE_DIR, "uploads", "dataset_staging")
    os.makedirs(staging_dir, exist_ok=True)
    coco_path = os.path.join(staging_dir, f"{job_id}.json")
    zip_path = os.path.join(staging_dir, f"{job_id}.zip")

    async def save_upload(upload: UploadFile, path: str):
        with open(path, "wb") as output:
            while chunk := await upload.read(8 * 1024 * 1024):
                output.write(chunk)

    try:
        await save_upload(coco_json_file, coco_path)
        await save_upload(images_zip_file, zip_path)
    except Exception:
        for path in (coco_path, zip_path):
            if os.path.exists(path):
                os.remove(path)
        raise

    with _dataset_jobs_lock:
        _dataset_jobs[job_id] = {
            "job_id": job_id, "status": "queued", "stage": "queued", "percentage": 0,
            "message": "Upload diterima dan menunggu pemrosesan.", "created_at": datetime.utcnow().isoformat()
        }
    background_tasks.add_task(_run_dataset_import, job_id, dataset_name or "cvat_dataset", coco_path, zip_path, project_id)
    return _dataset_jobs[job_id]


@router.get("/data/jobs/{job_id}")
def get_dataset_job(job_id: str):
    with _dataset_jobs_lock:
        job = _dataset_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job upload tidak ditemukan atau server telah dimulai ulang.")
        return dict(job)


def _dataset_payload(dataset: MLDataset, include_images: bool = False):
    artifacts = json.loads(dataset.artifacts or "{}")
    endpoint, bucket, _, _, _, _ = get_s3_credentials()

    def refresh_url(value):
        if not isinstance(value, str) or not value.startswith(f"{endpoint.rstrip('/')}/{bucket}/"):
            return value
        return get_storage_proxy_url(value) or value

    for key, value in list(artifacts.items()):
        if key.endswith("_url"):
            artifacts[key] = _stable_dataset_url(refresh_url(value))
    artifacts["label_studio_import_url"] = _dataset_import_url(dataset.id)

    instructions = artifacts.get("label_studio_instructions")
    if not isinstance(instructions, dict):
        instructions = {}
        artifacts["label_studio_instructions"] = instructions
    instructions["method_2_direct_import_url"] = artifacts["label_studio_import_url"]

    # Automatically generate / upgrade colab_training snippets with full dataset downloader
    yolo_yaml_url = artifacts.get("yolo_yaml_url")
    tasks_url = artifacts.get("tasks_json_url") or artifacts["label_studio_import_url"]
    coco_json_url = artifacts.get("coco_json_url")
    colab_notebooks = {
        "yolo": f"/api/v1/models/data/datasets/{dataset.id}/colab-notebook.ipynb?model=yolox",
        "yolox": f"/api/v1/models/data/datasets/{dataset.id}/colab-notebook.ipynb?model=yolox",
        "yolo26": f"/api/v1/models/data/datasets/{dataset.id}/colab-notebook.ipynb?model=yolo26",
        "rfdetr": f"/api/v1/models/data/datasets/{dataset.id}/colab-notebook.ipynb?model=rfdetr",
        "all": f"/api/v1/models/data/datasets/{dataset.id}/colab-notebook.ipynb?model=all"
    }
    colab_nb_url = colab_notebooks["yolox"]
    artifacts["colab_notebook_url"] = colab_nb_url
    artifacts["colab_notebooks"] = colab_notebooks

    if yolo_yaml_url:
        fresh_snippets = build_colab_snippets(
            folder_name=dataset.folder,
            yolo_yaml_url=yolo_yaml_url,
            tasks_url=tasks_url,
            coco_url=coco_json_url or ""
        )
        artifacts["colab_training"] = {
            "notebook_url": colab_nb_url,
            "data_yaml_url": yolo_yaml_url,
            "coco_json_url": coco_json_url,
            "yolo_code": fresh_snippets["yolo_code"],
            "yolo26_code": fresh_snippets["yolo26_code"],
            "rfdetr_code": fresh_snippets["rfdetr_code"]
        }

    payload = {
        "id": dataset.id, "name": dataset.name, "dataset_folder": dataset.folder,
        "status": dataset.status, "images_uploaded_count": dataset.image_count,
        "tasks_created_count": dataset.task_count, "categories": json.loads(dataset.categories or "[]"),
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
        **artifacts,
    }
    if include_images:
        images = json.loads(dataset.images or "[]")
        for image in images:
            image["url"] = _stable_dataset_url(refresh_url(image.get("url", "")))
        payload["images"] = images
    return payload


@router.get("/data/datasets/{dataset_id}/label-studio-tasks.json")
def get_label_studio_tasks(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(MLDataset).filter(MLDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")

    tasks_key = f"datasets/{dataset.folder}/label_studio_tasks.json"
    tasks = None
    signed_url = get_presigned_download_url(tasks_key)
    if signed_url:
        try:
            import requests
            response = requests.get(signed_url, timeout=15)
            response.raise_for_status()
            tasks = response.json()
        except Exception:
            tasks = None

    if tasks is None:
        local_path = os.path.join(s3_service.local_s3_dir, *tasks_key.split("/"))
        try:
            with open(local_path, "r", encoding="utf-8") as tasks_file:
                tasks = json.load(tasks_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail="File Label Studio dataset tidak ditemukan.") from exc

    if not isinstance(tasks, list):
        raise HTTPException(status_code=502, detail="Format task Label Studio tidak valid.")
    stored_images = json.loads(dataset.images or "[]")
    image_urls = {
        image.get("name"): image.get("url")
        for image in stored_images
        if isinstance(image, dict) and image.get("name") and image.get("url")
    }
    for task in tasks:
        if isinstance(task, dict) and isinstance(task.get("data"), dict):
            task["data"]["image"] = _dataset_image_url(
                task["data"].get("image", ""), dataset.folder, image_urls,
                task["data"].get("original_filename"),
            )
    return tasks


@router.get("/data/datasets/{dataset_id}/colab-notebook.ipynb")
def get_dataset_colab_notebook(
    dataset_id: str,
    model: str = Query("yolox"),
    mode: str = Query("colab"),         # "colab" | "local_cpu" | "local_gpu"
    weights: Optional[str] = Query(None),
    epochs: Optional[int] = Query(None),
    batch: Optional[int] = Query(None),
    imgsz: int = Query(640),
    optimizer: Optional[str] = Query(None),
    lr0: Optional[float] = Query(None),
    workers: Optional[int] = Query(None),
    patience: Optional[int] = Query(None),
    cos_lr: Optional[bool] = Query(True),
    close_mosaic: Optional[int] = Query(10),
    lrf: Optional[float] = Query(None),
    box: Optional[float] = Query(None),
    db: Session = Depends(get_db)
):
    dataset = db.query(MLDataset).filter(MLDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")
    artifacts = json.loads(dataset.artifacts or "{}")
    endpoint, bucket, _, _, _, _ = get_s3_credentials()

    def refresh_url(value):
        if not isinstance(value, str) or not value.startswith(f"{endpoint.rstrip('/')}/{bucket}/"):
            return value
        return get_storage_proxy_url(value) or value

    for key, value in list(artifacts.items()):
        if key.endswith("_url"):
            artifacts[key] = _stable_dataset_url(refresh_url(value))

    yolo_yaml_url = artifacts.get("yolo_yaml_url") or ""
    tasks_url = artifacts.get("tasks_json_url") or _dataset_import_url(dataset.id)
    coco_json_url = artifacts.get("coco_json_url") or ""

    colab_nb = generate_colab_notebook_dict(
        folder_name=dataset.folder,
        yolo_yaml_url=yolo_yaml_url,
        tasks_url=tasks_url,
        coco_url=coco_json_url,
        model_type=model,
        mode=mode,
        epochs=epochs,
        batch=batch,
        imgsz=imgsz,
        optimizer=optimizer,
        lr0=lr0,
        workers=workers,
        patience=patience,
        weights=weights,
        cos_lr=cos_lr,
        close_mosaic=close_mosaic,
        lrf=lrf,
        box=box,
    )
    content = json.dumps(colab_nb, indent=2)
    clean_model = (model or "yolox").lower().replace("-", "").replace("_", "")
    clean_mode = mode.lower().replace("-", "_") if mode else "colab"
    w_tag = f"_{weights.lower().replace('.pt', '')}" if weights else ""
    filename = f"raray_vision_{dataset.folder}_{clean_model}{w_tag}_{clean_mode}.ipynb"
    return Response(
        content=content,
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )



@router.get("/data/datasets")
def list_datasets(db: Session = Depends(get_db)):
    datasets = db.query(MLDataset).order_by(MLDataset.created_at.desc()).all()
    return {"datasets": [_dataset_payload(item) for item in datasets]}


@router.get("/data/datasets/{dataset_id}")
def get_dataset(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(MLDataset).filter(MLDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")
    return _dataset_payload(dataset, include_images=True)


@router.patch("/data/datasets/{dataset_id}")
def update_dataset(dataset_id: str, payload: DatasetUpdateRequest, db: Session = Depends(get_db)):
    dataset = db.query(MLDataset).filter(MLDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Nama dataset tidak boleh kosong.")
    dataset.name = clean_name
    db.commit()
    db.refresh(dataset)
    return _dataset_payload(dataset)


@router.delete("/data/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, delete_files: bool = Query(False), db: Session = Depends(get_db)):
    dataset = db.query(MLDataset).filter(MLDataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")
    if delete_files:
        local_path = os.path.join(s3_service.local_s3_dir, "datasets", dataset.folder)
        if os.path.isdir(local_path):
            shutil.rmtree(local_path)
    db.delete(dataset)
    db.commit()
    return {"success": True, "message": "Dataset dihapus dari riwayat."}


@router.post("/predict-video")
async def predict_video_endpoint(
    video: UploadFile = File(...),
    conf_threshold: float = Form(0.25),
    iou_threshold: float = Form(0.45)
):
    """
    Run object detection on an uploaded video file frame-by-frame.
    Returns URL to web-compatible MP4 with rendered bounding boxes and stats.
    """
    video_bytes = await video.read()
    if not video_bytes:
        raise HTTPException(status_code=400, detail="File video kosong")

    import asyncio
    try:
        result = await asyncio.to_thread(
            detection_service.predict_video,
            video_bytes,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold
        )
        return {
            "status": "success",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memproses video: {str(e)}")


# ==========================================
# 5. Serving Endpoints (Multi-Model API Hub)
# ==========================================

import re

def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-') or f"ep-{uuid.uuid4().hex[:6]}"

@router.get("/endpoints")
def list_endpoints(db: Session = Depends(get_db)):
    """List all custom serving endpoints with joined model information."""
    endpoints = db.query(MLEndpoint).order_by(MLEndpoint.created_at.desc()).all()
    results = []
    for ep in endpoints:
        m = db.query(MLModel).filter(MLModel.id == ep.model_id).first() if ep.model_id else None
        results.append({
            "id": ep.id,
            "name": ep.name,
            "slug": ep.slug,
            "description": ep.description,
            "model_id": ep.model_id,
            "model_name": m.name if m else "(Tidak Ada Model)",
            "model_version": m.version if m else "-",
            "model_framework": m.framework if m else "-",
            "is_active": ep.is_active,
            "default_conf": ep.default_conf,
            "default_iou": ep.default_iou,
            "total_requests": ep.total_requests or 0,
            "last_accessed_at": ep.last_accessed_at.isoformat() if ep.last_accessed_at else None,
            "created_at": ep.created_at.isoformat() if ep.created_at else None,
            "predict_url": f"/api/v1/models/endpoints/{ep.slug}/predict",
            "predict_video_url": f"/api/v1/models/endpoints/{ep.slug}/predict-video"
        })
    return {"endpoints": results}


@router.post("/endpoints")
def create_endpoint(payload: EndpointCreateRequest, db: Session = Depends(get_db)):
    """Create a new custom serving endpoint assigned to a model."""
    raw_slug = payload.slug if (payload.slug and payload.slug.strip()) else slugify(payload.name)
    clean_slug = slugify(raw_slug)

    # Check slug uniqueness
    existing = db.query(MLEndpoint).filter(MLEndpoint.slug == clean_slug).first()
    if existing:
        clean_slug = f"{clean_slug}-{uuid.uuid4().hex[:4]}"

    # Verify model_id if given
    if payload.model_id:
        m = db.query(MLModel).filter(MLModel.id == payload.model_id).first()
        if not m:
            raise HTTPException(status_code=404, detail=f"Model ID {payload.model_id} tidak ditemukan.")

    new_ep = MLEndpoint(
        name=payload.name.strip(),
        slug=clean_slug,
        description=payload.description.strip() if payload.description else None,
        model_id=payload.model_id,
        is_active=payload.is_active,
        default_conf=payload.default_conf,
        default_iou=payload.default_iou,
        total_requests=0
    )
    db.add(new_ep)
    db.commit()
    db.refresh(new_ep)

    return {
        "success": True,
        "message": f"Serving endpoint '{new_ep.name}' berhasil dibuat!",
        "endpoint": {
            "id": new_ep.id,
            "name": new_ep.name,
            "slug": new_ep.slug,
            "predict_url": f"/api/v1/models/endpoints/{new_ep.slug}/predict",
            "model_id": new_ep.model_id
        }
    }


@router.put("/endpoints/{endpoint_id}")
def update_endpoint(endpoint_id: int, payload: EndpointUpdateRequest, db: Session = Depends(get_db)):
    """Update serving endpoint configuration."""
    ep = db.query(MLEndpoint).filter(MLEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint tidak ditemukan")

    if payload.name is not None and payload.name.strip():
        ep.name = payload.name.strip()
    if payload.slug is not None and payload.slug.strip():
        target_slug = slugify(payload.slug)
        duplicate = db.query(MLEndpoint).filter(MLEndpoint.slug == target_slug, MLEndpoint.id != endpoint_id).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="Slug endpoint sudah digunakan.")
        ep.slug = target_slug
    if payload.description is not None:
        ep.description = payload.description.strip()
    if payload.model_id is not None:
        m = db.query(MLModel).filter(MLModel.id == payload.model_id).first()
        if not m:
            raise HTTPException(status_code=404, detail=f"Model ID {payload.model_id} tidak ditemukan.")
        ep.model_id = payload.model_id
    if payload.is_active is not None:
        ep.is_active = payload.is_active
    if payload.default_conf is not None:
        ep.default_conf = payload.default_conf
    if payload.default_iou is not None:
        ep.default_iou = payload.default_iou

    db.commit()
    db.refresh(ep)

    return {
        "success": True,
        "message": f"Endpoint '{ep.name}' berhasil diperbarui.",
        "endpoint": {
            "id": ep.id,
            "name": ep.name,
            "slug": ep.slug,
            "model_id": ep.model_id,
            "is_active": ep.is_active
        }
    }


@router.put("/endpoints/{endpoint_id}/switch-model")
def switch_endpoint_model(endpoint_id: int, payload: EndpointSwitchModelRequest, db: Session = Depends(get_db)):
    """
    Instantly switch the target model connected to this endpoint.
    Clients calling the endpoint will immediately use the new model without URL change!
    """
    ep = db.query(MLEndpoint).filter(MLEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint tidak ditemukan")

    target_model = db.query(MLModel).filter(MLModel.id == payload.model_id).first()
    if not target_model:
        raise HTTPException(status_code=404, detail=f"Model ID {payload.model_id} tidak ditemukan di registry")

    old_model_id = ep.model_id
    ep.model_id = target_model.id
    db.commit()
    db.refresh(ep)

    return {
        "success": True,
        "message": f"Berhasil mengalihkan endpoint '{ep.name}' ke model '{target_model.name} ({target_model.version})'!",
        "endpoint_slug": ep.slug,
        "previous_model_id": old_model_id,
        "current_model": {
            "id": target_model.id,
            "name": target_model.name,
            "version": target_model.version,
            "framework": target_model.framework
        }
    }


@router.delete("/endpoints/{endpoint_id}")
def delete_endpoint(endpoint_id: int, db: Session = Depends(get_db)):
    """Delete a custom serving endpoint."""
    ep = db.query(MLEndpoint).filter(MLEndpoint.id == endpoint_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Endpoint tidak ditemukan")

    name = ep.name
    db.delete(ep)
    db.commit()
    return {"success": True, "message": f"Serving endpoint '{name}' berhasil dihapus."}


@router.post("/endpoints/{slug}/predict")
async def predict_via_endpoint(
    slug: str,
    file: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    conf_threshold: Optional[float] = Form(None),
    iou_threshold: Optional[float] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Run detection inference specifically through the assigned endpoint and its connected model.
    """
    ep = db.query(MLEndpoint).filter(MLEndpoint.slug == slug).first()
    if not ep:
        raise HTTPException(status_code=404, detail=f"Serving endpoint '{slug}' tidak ditemukan")

    if not ep.is_active:
        raise HTTPException(status_code=403, detail=f"Serving endpoint '{slug}' sedang dinonaktifkan")

    # Image payload
    if file:
        image_bytes = await file.read()
        filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}.jpg"
    elif image_url:
        import requests
        try:
            resp = requests.get(image_url, timeout=10)
            resp.raise_for_status()
            image_bytes = resp.content
            filename = os.path.basename(image_url.split("?")[0]) or "remote_image.jpg"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Gagal mengambil gambar dari URL: {e}")
    else:
        raise HTTPException(status_code=400, detail="Wajib menyertakan file gambar atau image_url")

    # Threshold fallback to endpoint defaults
    c_thresh = conf_threshold if conf_threshold is not None else ep.default_conf
    i_thresh = iou_threshold if iou_threshold is not None else ep.default_iou

    # Run inference with endpoint's assigned model
    try:
        result = detection_service.predict(
            image_bytes,
            conf_threshold=c_thresh,
            iou_threshold=i_thresh,
            model_id=ep.model_id,
            db=db
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error pada endpoint '{slug}': {str(e)}")

    pred_id = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".jpg"

    raw_s3_key = f"datasets/raw/{pred_id}{ext}"
    orig_url = s3_service.upload_bytes(image_bytes, raw_s3_key, content_type="image/jpeg")

    annotated_s3_key = f"datasets/annotated/{pred_id}.jpg"
    annotated_url = s3_service.upload_bytes(result["annotated_bytes"], annotated_s3_key, content_type="image/jpeg")

    # Feedback logic with audit sampling
    import random
    initial_status = "pending"
    is_audit = False
    if result["top_confidence"] >= 0.88 and result["detection_count"] > 0:
        if random.random() < 0.10:
            initial_status = "audit_required"
            is_audit = True
        else:
            initial_status = "auto_labeled"

    # Store prediction record in DB with endpoint tag
    pred_record = MLPrediction(
        id=pred_id,
        model_id=result["model_id"],
        model_version=result["model_version"],
        endpoint_slug=ep.slug,
        original_image_url=orig_url,
        annotated_image_url=annotated_url,
        detections=json.dumps(result["detections"]),
        top_confidence=result["top_confidence"],
        detection_count=result["detection_count"],
        latency_ms=result["latency_ms"],
        feedback_status=initial_status,
        is_audit_sample=is_audit,
        image_quality=json.dumps(result.get("quality", {})),
        image_width=result.get("image_width"),
        image_height=result.get("image_height"),
        is_synced_to_ls=False
    )
    db.add(pred_record)

    # Update endpoint stats
    import datetime
    ep.total_requests = (ep.total_requests or 0) + 1
    ep.last_accessed_at = datetime.datetime.utcnow()

    db.commit()

    return {
        "prediction_id": pred_id,
        "endpoint": {
            "name": ep.name,
            "slug": ep.slug
        },
        "model_id": result["model_id"],
        "model_name": result["model_name"],
        "model_version": result["model_version"],
        "original_image_url": orig_url,
        "annotated_image_url": annotated_url,
        "detections": result["detections"],
        "detection_count": result["detection_count"],
        "top_confidence": result["top_confidence"],
        "latency_ms": result["latency_ms"],
        "image_width": result["image_width"],
        "image_height": result["image_height"],
        "quality": result.get("quality", {}),
        "feedback_status": initial_status,
        "is_audit_sample": is_audit
    }


@router.post("/endpoints/{slug}/predict-video")
async def predict_video_via_endpoint(
    slug: str,
    video: UploadFile = File(...),
    conf_threshold: Optional[float] = Form(None),
    iou_threshold: Optional[float] = Form(None),
    db: Session = Depends(get_db)
):
    """Run video inference specifically through the assigned endpoint and its connected model."""
    ep = db.query(MLEndpoint).filter(MLEndpoint.slug == slug).first()
    if not ep:
        raise HTTPException(status_code=404, detail=f"Serving endpoint '{slug}' tidak ditemukan")

    if not ep.is_active:
        raise HTTPException(status_code=403, detail=f"Serving endpoint '{slug}' sedang dinonaktifkan")

    video_bytes = await video.read()
    if not video_bytes:
        raise HTTPException(status_code=400, detail="File video kosong")

    c_thresh = conf_threshold if conf_threshold is not None else ep.default_conf
    i_thresh = iou_threshold if iou_threshold is not None else ep.default_iou

    import asyncio
    try:
        result = await asyncio.to_thread(
            detection_service.predict_video,
            video_bytes,
            conf_threshold=c_thresh,
            iou_threshold=i_thresh,
            model_id=ep.model_id,
            db=db
        )
        # Update endpoint stats
        import datetime
        ep.total_requests = (ep.total_requests or 0) + 1
        ep.last_accessed_at = datetime.datetime.utcnow()
        db.commit()

        return {
            "status": "success",
            "endpoint": {"name": ep.name, "slug": ep.slug},
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memproses video pada endpoint '{slug}': {str(e)}")
