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
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status, BackgroundTasks
from fastapi.responses import JSONResponse, Response, FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

try:
    from backend.app.database.database import get_db
    from backend.app.database.models import MLModel, MLPrediction, MLEndpoint, MLDataset
    from backend.app.database.database import SessionLocal
    from backend.app.services.detection_service import detection_service
    from backend.app.services.s3_service import s3_service, get_storage_proxy_url, get_presigned_download_url, get_s3_credentials
    from backend.app.services.label_studio_service import label_studio_service
    from backend.app.core.config import BASE_DIR
except ImportError:
    from app.database.database import get_db
    from app.database.models import MLModel, MLPrediction, MLEndpoint, MLDataset
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
# Dataset: {folder_name}
# ==========================================
!pip install -q ultralytics pyyaml requests tqdm

# 1. Download & Prepare Dataset Locally
{dataset_setup_script}

# 2. Train YOLO-X (200 Epochs, T4 GPU)
from ultralytics import YOLO

model = YOLO("yolo11x.pt") # YOLO-X architecture
results = model.train(data="data.yaml", epochs=200, imgsz=640, device=0, batch=16, optimizer="AdamW")

# 3. Validasi Model
metrics = model.val()
print("mAP50-95:", metrics.box.map)

# 4. Export ONNX untuk Hot-Swap di Raray Vision
model.export(format="onnx")
"""

    yolo26_code = f"""# ==========================================
# 🔥 GOOGLE COLAB TRAINING PIPELINE (YOLO-26: 200 EPOCHS, T4 GPU)
# Dataset: {folder_name}
# ==========================================
!pip install -q ultralytics pyyaml requests tqdm

# 1. Download & Prepare Dataset Locally
{dataset_setup_script}

# 2. Train YOLO-26 (200 Epochs, T4 GPU)
from ultralytics import YOLO

model = YOLO("yolo11m.pt")
results = model.train(data="data.yaml", epochs=200, imgsz=640, device=0, batch=24, optimizer="SGD")

# 3. Validasi Model
metrics = model.val()
print("mAP50-95:", metrics.box.map)

# 4. Export ONNX untuk Hot-Swap di Raray Vision
model.export(format="onnx")
"""

    rfdetr_code = f"""# ==========================================
# 🎯 GOOGLE COLAB TRAINING PIPELINE (RF-DETR / RT-DETR: 200 EPOCHS, T4 GPU)
# Dataset: {folder_name}
# ==========================================
!pip install -q ultralytics pyyaml requests tqdm

# 1. Download & Prepare Dataset Locally
{dataset_setup_script}

# 2. Train RF-DETR / RT-DETR (200 Epochs, T4 GPU)
from ultralytics import RTDETR

model = RTDETR("rtdetr-l.pt")
results = model.train(data="data.yaml", epochs=200, imgsz=640, device=0, batch=12)

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


def generate_colab_notebook_dict(folder_name: str, yolo_yaml_url: str, tasks_url: str, coco_url: str) -> dict:
    public_app_url = PUBLIC_APP_URL
    colab_cells = [
        # HEADER
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                f"# 📘 Tutorial & Panduan: Training Model Deep Learning di Google Colab\n",
                f"**Dataset:** `{folder_name}`  \n",
                f"**Target Hardware:** NVIDIA T4 GPU  \n",
                f"**Mode Training:** Modular (Step-by-Step / Per-Code)  \n",
                f"**Model Didukung:**\n",
                f"1. ⚡ **YOLO-X / YOLO11-X** (High-Performance Real-Time Object Detection)\n",
                f"2. 🔥 **YOLO-26 / Edge Variant** (Ultra Fast Architecture for Edge Devices)\n",
                f"3. 🎯 **RF-DETR / RT-DETR** (Real-Time Transformer Object Detection)\n",
                f"\n",
                f"---\n",
                f"Notebook ini dirancang secara **modular (per-code slice)**. Anda dapat menjalankan cell satu per satu untuk memantau proses, menguji coba sampel data terlebih dahulu, memahami cara kerja setiap tahapan, dan melakukan debugging jika diperlukan."
            ]
        },
        # LANGKAH 0
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 🖥️ Langkah 0: Cek Akses GPU (Runtime Check)\n",
                "Sebelum memulai training model Deep Learning, kita harus memastikan bahwa runtime Google Colab menggunakan **GPU (Graphics Processing Unit)** seperti **Tesla T4** agar proses training berjalan cepat."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
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
                "    print('[WARNING] GPU tidak terdeteksi! Silakan ganti runtime ke T4 GPU via menu: Runtime > Change runtime type > T4 GPU.')\n"
            ]
        },
        # LANGKAH 1
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 📦 Langkah 1: Instalasi Library & Dependensi\n",
                "Menginstal library utama: `ultralytics` (untuk YOLO & RT-DETR), `onnx` (untuk export model), `pyyaml` (konfigurasi dataset), dan `tqdm` (indikator progress)."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "!pip install -q --upgrade ultralytics onnx onnxruntime onnxsim pyyaml requests urllib3 tqdm\n",
                "import ultralytics\n",
                "print(f'Ultralytics Version: {ultralytics.__version__}')\n",
                "ultralytics.checks()\n"
            ]
        },
        # LANGKAH 2
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### ⚙️ Langkah 2: Konfigurasi URL & Inisialisasi Direktori Dataset\n",
                "Menyiapkan folder lokal di Colab (`/content/dataset/images/train`, `/content/dataset/images/val`, dll) dan inisialisasi session HTTP dengan connection pool & auto-retry 5x."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import os, glob, shutil, time, requests, yaml, json\n",
                "from requests.adapters import HTTPAdapter\n",
                "from urllib3.util.retry import Retry\n",
                "\n",
                f"APP_URL = \"{public_app_url}\"\n",
                f"YOLO_YAML_URL = \"{yolo_yaml_url}\"\n",
                f"COCO_JSON_URL = \"{coco_url}\"\n",
                f"TASKS_JSON_URL = \"{tasks_url}\"\n",
                "\n",
                "# Setup Session Jaringan dengan Auto-Retry\n",
                "session = requests.Session()\n",
                "retries = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)\n",
                "adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)\n",
                "session.mount('https://', adapter)\n",
                "session.mount('http://', adapter)\n",
                "\n",
                "# Inisialisasi struktur direktori YOLO di Colab\n",
                "base_dir = os.path.abspath('dataset')\n",
                "train_img_dir = os.path.join(base_dir, 'images', 'train')\n",
                "val_img_dir = os.path.join(base_dir, 'images', 'val')\n",
                "train_lbl_dir = os.path.join(base_dir, 'labels', 'train')\n",
                "val_lbl_dir = os.path.join(base_dir, 'labels', 'val')\n",
                "\n",
                "for p in [train_img_dir, val_img_dir, train_lbl_dir, val_lbl_dir]:\n",
                "    os.makedirs(p, exist_ok=True)\n",
                "\n",
                "print('✓ Direktori dataset siap di:', base_dir)\n"
            ]
        },
        # LANGKAH 3
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 📄 Langkah 3: Unduh & Periksa File `data.yaml`\n",
                "File `data.yaml` berisi definisi kelas/kategori objek dan pemetaan ID label."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "print(f'Mengunduh data.yaml dari: {YOLO_YAML_URL}')\n",
                "try:\n",
                "    r_yaml = session.get(YOLO_YAML_URL, timeout=(10, 60))\n",
                "    if r_yaml.status_code == 200:\n",
                "        with open('data.yaml', 'wb') as f:\n",
                "            f.write(r_yaml.content)\n",
                "        print('✓ File data.yaml berhasil diunduh!')\n",
                "    else:\n",
                "        print(f'Warning: HTTP {r_yaml.status_code} saat mengunduh data.yaml')\n",
                "except Exception as e:\n",
                "    print(f'Error: {e}')\n",
                "\n",
                "# Baca dan periksa pemetaan kelas\n",
                "with open('data.yaml', 'r') as f:\n",
                "    data_cfg = yaml.safe_load(f) or {}\n",
                "\n",
                "raw_names = data_cfg.get('names', {0: 'object'})\n",
                "if isinstance(raw_names, dict):\n",
                "    name_to_id = {str(v).lower(): int(k) for k, v in raw_names.items()}\n",
                "elif isinstance(raw_names, list):\n",
                "    name_to_id = {str(v).lower(): i for i, v in enumerate(raw_names)}\n",
                "else:\n",
                "    name_to_id = {'object': 0}\n",
                "\n",
                "print(f'Total Kelas Terdaftar: {len(name_to_id)}')\n",
                "print('Daftar Kelas (ID -> Nama):')\n",
                "items_to_show = list(raw_names.items() if isinstance(raw_names, dict) else enumerate(raw_names))\n",
                "for k, v in items_to_show[:10]:\n",
                "    print(f'  [{k}] {v}')\n",
                "if len(items_to_show) > 10:\n",
                "    print(f'  ... dan {len(items_to_show) - 10} kelas lainnya.')\n"
            ]
        },
        # LANGKAH 4
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 📋 Langkah 4: Unduh Metadata Task Anotasi (`tasks.json`)\n",
                "Mengunduh file metadata anotasi yang berisi informasi bounding box setiap gambar dari server Raray Vision."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "print(f'Mengunduh metadata anotasi dari: {TASKS_JSON_URL}')\n",
                "tasks = []\n",
                "try:\n",
                "    r_tasks = session.get(TASKS_JSON_URL, timeout=(15, 90))\n",
                "    if r_tasks.status_code == 200:\n",
                "        tasks = r_tasks.json()\n",
                "        print(f'✓ Berhasil memuat {len(tasks)} total tasks anotasi!')\n",
                "        if tasks:\n",
                "            t0 = tasks[0]\n",
                "            print('\\nPreview Task 0:')\n",
                "            print('  - File Name      :', t0.get('data', {}).get('original_filename'))\n",
                "            print('  - Raw Image URL  :', t0.get('data', {}).get('image'))\n",
                "            print('  - Jumlah Anotasi :', len(t0.get('annotations', [{}])[0].get('result', [])))\n",
                "    else:\n",
                "        print(f'Warning: HTTP {r_tasks.status_code} saat mengunduh tasks.json')\n",
                "except Exception as e:\n",
                "    print(f'Error: {e}')\n"
            ]
        },
        # LANGKAH 5
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 🧪 Langkah 5: Smoke Test (Uji Coba Unduh 5 Gambar Pertama)\n",
                "**Langkah ini sangat penting!** Sebelum mendownload ribuan gambar selama puluhan menit, kita lakukan uji coba mengunduh 5 gambar pertama untuk memverifikasi koneksi, perutean proxy terautentikasi, dan status HTTP 200 OK."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "# Fungsi pembantu untuk konversi URL S3 ke proxy publik terautentikasi\n",
                "def resolve_image_url(raw_url):\n",
                "    if not raw_url:\n",
                "        return ''\n",
                "    if 'is3.cloudhost.id/onechitra/' in raw_url:\n",
                "        return raw_url.replace('https://is3.cloudhost.id/onechitra/', f'{APP_URL}/api/v1/uploads/').replace('http://is3.cloudhost.id/onechitra/', f'{APP_URL}/api/v1/uploads/')\n",
                "    elif raw_url.startswith('/api/v1/uploads/'):\n",
                "        return f'{APP_URL}{raw_url}'\n",
                "    return raw_url\n",
                "\n",
                "print('=== SMOKE TEST: UJI COBA UNDUH 5 GAMBAR PERTAMA ===')\n",
                "test_samples = tasks[:5]\n",
                "success_cnt = 0\n",
                "for i, t in enumerate(test_samples):\n",
                "    orig_url = t.get('data', {}).get('image', '')\n",
                "    resolved_url = resolve_image_url(orig_url)\n",
                "    fname = t.get('data', {}).get('original_filename') or os.path.basename(orig_url.split('?')[0]) or f'test_{i}.jpg'\n",
                "    try:\n",
                "        res = session.get(resolved_url, timeout=(10, 30))\n",
                "        if res.status_code == 200:\n",
                "            success_cnt += 1\n",
                "            print(f'[{i+1}/5] ✓ {fname} -> HTTP 200 OK ({len(res.content)/1024:.1f} KB)')\n",
                "        elif res.status_code == 403 and ('is3.cloudhost.id' in orig_url or 'onechitra' in orig_url):\n",
                "            suffix = orig_url.split('/onechitra/')[-1] if '/onechitra/' in orig_url else orig_url.split('.id/')[-1]\n",
                "            fallback_url = f'{APP_URL}/api/v1/uploads/{suffix.lstrip(\"/\")}'\n",
                "            res_fb = session.get(fallback_url, timeout=(10, 30))\n",
                "            if res_fb.status_code == 200:\n",
                "                success_cnt += 1\n",
                "                print(f'[{i+1}/5] ✓ {fname} via Fallback Proxy -> HTTP 200 OK ({len(res_fb.content)/1024:.1f} KB)')\n",
                "            else:\n",
                "                print(f'[{i+1}/5] ✗ {fname} -> HTTP {res_fb.status_code}')\n",
                "        else:\n",
                "            print(f'[{i+1}/5] ✗ {fname} -> HTTP {res.status_code}')\n",
                "    except Exception as err:\n",
                "        print(f'[{i+1}/5] ✗ {fname} -> Error: {err}')\n",
                "\n",
                "print(f'\\nHasil Smoke Test: {success_cnt}/5 gambar berhasil terhubung!')\n",
                "if success_cnt > 0:\n",
                "    print('✓ Jalur pengunduhan terverifikasi! Anda dapat melanjutkan ke Langkah 6.')\n",
                "else:\n",
                "    print('✗ Gagal mengunduh sampel gambar. Periksa bahwa server Raray Vision aktif.')\n"
            ]
        },
        # LANGKAH 6
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 📥 Langkah 6: Unduh Seluruh Gambar Dataset Secara Paralel\n",
                "Mengunduh gambar dan membuat file anotasi label YOLO `.txt` (80% Train, 20% Val).\n",
                "\n",
                "> **Tips Belajar:** Anda dapat mengubah nilai `LIMIT_DOWNLOAD = None` menjadi angka tertentu (contoh: `100` atau `300`) jika ingin melakukan training uji coba cepat tanpa menunggu semua 3.500+ gambar."
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from concurrent.futures import ThreadPoolExecutor\n",
                "from tqdm import tqdm\n",
                "\n",
                "# Atur limit gambar jika ingin training cepat (misal: 200), atau None untuk seluruh dataset\n",
                "LIMIT_DOWNLOAD = None  # Contoh: 200 untuk uji coba, atau None untuk semua gambar\n",
                "\n",
                "active_tasks = tasks[:LIMIT_DOWNLOAD] if LIMIT_DOWNLOAD else tasks\n",
                "print(f'Memulai download {len(active_tasks)} gambar dengan 6 worker paralel...')\n",
                "\n",
                "def download_and_process_item(item_data):\n",
                "    idx, item = item_data\n",
                "    img_url = resolve_image_url(item.get('data', {}).get('image', ''))\n",
                "    if not img_url:\n",
                "        return\n",
                "    fname = item.get('data', {}).get('original_filename') or os.path.basename(img_url.split('?')[0]) or f'img_{idx}.jpg'\n",
                "    if not fname.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp')):\n",
                "        fname = f'img_{idx}.jpg'\n",
                "    split = 'val' if (len(active_tasks) > 1 and idx % 5 == 0) else 'train'\n",
                "    dest_img = os.path.join(base_dir, 'images', split, fname)\n",
                "    dest_lbl = os.path.join(base_dir, 'labels', split, os.path.splitext(fname)[0] + '.txt')\n",
                "\n",
                "    for attempt in range(3):\n",
                "        try:\n",
                "            res = session.get(img_url, timeout=(15, 60), stream=True)\n",
                "            if res.status_code == 403 and ('is3.cloudhost.id' in img_url or 'onechitra' in img_url):\n",
                "                suffix = img_url.split('/onechitra/')[-1] if '/onechitra/' in img_url else img_url.split('.id/')[-1]\n",
                "                fallback_url = f'{APP_URL}/api/v1/uploads/{suffix.lstrip(\"/\")}'\n",
                "                res = session.get(fallback_url, timeout=(15, 60), stream=True)\n",
                "\n",
                "            if res.status_code == 200:\n",
                "                with open(dest_img, 'wb') as f:\n",
                "                    for chunk in res.iter_content(chunk_size=65536):\n",
                "                        if chunk:\n",
                "                            f.write(chunk)\n",
                "                lines = []\n",
                "                for ann in item.get('annotations', [{}])[0].get('result', []):\n",
                "                    val = ann.get('value', {})\n",
                "                    lbls = val.get('rectanglelabels', ['object'])\n",
                "                    first_lbl = str(lbls[0]).lower() if lbls else 'object'\n",
                "                    cid = name_to_id.get(first_lbl, 0)\n",
                "                    x_pct = val.get('x', 0) / 100.0\n",
                "                    y_pct = val.get('y', 0) / 100.0\n",
                "                    w_pct = val.get('width', 0) / 100.0\n",
                "                    h_pct = val.get('height', 0) / 100.0\n",
                "                    xc = x_pct + (w_pct / 2.0)\n",
                "                    yc = y_pct + (h_pct / 2.0)\n",
                "                    lines.append(f'{cid} {xc:.6f} {yc:.6f} {w_pct:.6f} {h_pct:.6f}')\n",
                "                with open(dest_lbl, 'w') as lf:\n",
                "                    lf.write('\\n'.join(lines))\n",
                "                return\n",
                "            elif res.status_code == 404:\n",
                "                return\n",
                "        except Exception:\n",
                "            if attempt < 2:\n",
                "                time.sleep(1 + attempt)\n",
                "\n",
                "with ThreadPoolExecutor(max_workers=6) as ex:\n",
                "    list(tqdm(ex.map(download_and_process_item, enumerate(active_tasks)), total=len(active_tasks)))\n",
                "\n",
                "# Fallback: pastikan train dan val selalu memiliki minimal 1 file gambar & label\n",
                "train_imgs = glob.glob(os.path.join(train_img_dir, '*.*'))\n",
                "val_imgs = glob.glob(os.path.join(val_img_dir, '*.*'))\n",
                "if not val_imgs and train_imgs:\n",
                "    for f in train_imgs[:max(1, len(train_imgs)//5)]:\n",
                "        shutil.copy(f, val_img_dir)\n",
                "        lbl_src = os.path.join(train_lbl_dir, os.path.splitext(os.path.basename(f))[0] + '.txt')\n",
                "        if os.path.exists(lbl_src): shutil.copy(lbl_src, val_lbl_dir)\n",
                "elif not train_imgs and val_imgs:\n",
                "    for f in val_imgs:\n",
                "        shutil.copy(f, train_img_dir)\n",
                "        lbl_src = os.path.join(val_lbl_dir, os.path.splitext(os.path.basename(f))[0] + '.txt')\n",
                "        if os.path.exists(lbl_src): shutil.copy(lbl_src, train_lbl_dir)\n",
                "\n",
                "# Update data.yaml path ke absolute path dataset\n",
                "data_cfg['path'] = base_dir\n",
                "data_cfg['train'] = 'images/train'\n",
                "data_cfg['val'] = 'images/val'\n",
                "with open('data.yaml', 'w') as f:\n",
                "    yaml.dump(data_cfg, f, sort_keys=False)\n",
                "\n",
                "print('✓ Pengunduhan selesai!')\n"
            ]
        },
        # LANGKAH 7
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 🔍 Langkah 7: Verifikasi & Inspeksi Dataset Lokal\n",
                "Memeriksa jumlah file gambar dan file label di folder `train` dan `val`, serta memastikan dataset siap dipakai untuk training."
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
                "print('=== HASIL PERSIAPAN DATASET LOKAL ===')\n",
                "print(f'Total Gambar Train : {len(train_imgs)}')\n",
                "print(f'Total Label Train  : {len(train_lbls)}')\n",
                "print(f'Total Gambar Val   : {len(val_imgs)}')\n",
                "print(f'Total Label Val    : {len(val_lbls)}')\n",
                "\n",
                "if len(train_imgs) == 0:\n",
                "    raise RuntimeError('Dataset train kosong (0 gambar)! Periksa kembali koneksi atau jalankan ulang Langkah 6.')\n",
                "\n",
                "# Tampilkan contoh isi file label txt\n",
                "sample_lbl = train_lbls[0] if train_lbls else None\n",
                "if sample_lbl:\n",
                "    print(f'\\nContoh Format Label ({os.path.basename(sample_lbl)}):')\n",
                "    with open(sample_lbl, 'r') as lf:\n",
                "        print(lf.read().strip())\n",
                "\n",
                "print('\\n✓ Konfigurasi data.yaml akhir:')\n",
                "!cat data.yaml\n"
            ]
        },
        # LANGKAH 8: YOLO-X
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### ⚡ Langkah 8: MODEL 1 - Training YOLO-X / YOLO11-X (200 Epochs, T4 GPU)\n",
                "**YOLO-X** adalah model arsitektur besar untuk akurasi tertinggi dalam deteksi objek real-time.\n",
                "- **Pretrained Weights:** `yolo11x.pt`\n",
                "- **Epochs:** `200`\n",
                "- **Optimizer:** `AdamW`\n",
                "- **Batch Size:** `16` (Optimal untuk VRAM 16GB Tesla T4)"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from ultralytics import YOLO\n",
                "\n",
                "print('🚀 MEMULAI TRAINING YOLO-X (200 EPOCHS)...')\n",
                "model_yolox = YOLO('yolo11x.pt')\n",
                "\n",
                "results_yolox = model_yolox.train(\n",
                "    data='data.yaml',\n",
                "    epochs=200,\n",
                "    imgsz=640,\n",
                "    batch=16,\n",
                "    device=0, # GPU 0 (Tesla T4)\n",
                "    workers=4,\n",
                "    optimizer='AdamW',\n",
                "    lr0=0.001,\n",
                "    patience=50,\n",
                "    save=True,\n",
                "    project='raray_vision_runs',\n",
                "    name='yolo_x_200epochs'\n",
                ")\n",
                "\n",
                "print('\\n📊 VALIDASI YOLO-X:')\n",
                "metrics_yolox = model_yolox.val()\n",
                "print('mAP50    :', metrics_yolox.box.map50)\n",
                "print('mAP50-95 :', metrics_yolox.box.map)\n",
                "\n",
                "# Export ke format ONNX\n",
                "model_yolox.export(format='onnx', dynamic=True, simplify=True)\n",
                "print('✓ YOLO-X weights & ONNX berhasil diekspor!')\n"
            ]
        },
        # LANGKAH 9: YOLO-26
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 🔥 Langkah 9: MODEL 2 - Training YOLO-26 (Edge Variant, 200 Epochs, T4 GPU)\n",
                "**YOLO-26** dirancang untuk perangkat Edge (Raspberry Pi, Jetson Nano, Mini PC) dengan FPS tinggi dan konsumsi memori rendah.\n",
                "- **Pretrained Weights:** `yolo11m.pt`\n",
                "- **Epochs:** `200`\n",
                "- **Optimizer:** `SGD`\n",
                "- **Batch Size:** `24`"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from ultralytics import YOLO\n",
                "\n",
                "print('🔥 MEMULAI TRAINING YOLO-26 VARIANT (200 EPOCHS)...')\n",
                "model_yolo26 = YOLO('yolo11m.pt')\n",
                "\n",
                "results_yolo26 = model_yolo26.train(\n",
                "    data='data.yaml',\n",
                "    epochs=200,\n",
                "    imgsz=640,\n",
                "    batch=24,\n",
                "    device=0,\n",
                "    workers=4,\n",
                "    optimizer='SGD',\n",
                "    lr0=0.01,\n",
                "    patience=50,\n",
                "    save=True,\n",
                "    project='raray_vision_runs',\n",
                "    name='yolo_26_200epochs'\n",
                ")\n",
                "\n",
                "print('\\n📊 VALIDASI YOLO-26:')\n",
                "metrics_yolo26 = model_yolo26.val()\n",
                "print('mAP50    :', metrics_yolo26.box.map50)\n",
                "print('mAP50-95 :', metrics_yolo26.box.map)\n",
                "\n",
                "# Export ke ONNX\n",
                "model_yolo26.export(format='onnx', dynamic=True, simplify=True)\n",
                "print('✓ YOLO-26 weights & ONNX berhasil diekspor!')\n"
            ]
        },
        # LANGKAH 10: RF-DETR
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 🎯 Langkah 10: MODEL 3 - Training RF-DETR / RT-DETR (Transformer, 200 Epochs, T4 GPU)\n",
                "**RF-DETR / RT-DETR** adalah arsitektur Transformer Vision State-of-the-Art yang tidak membutuhkan Non-Maximum Suppression (NMS), sangat unggul untuk deteksi objek padat dan tumpang tindih.\n",
                "- **Pretrained Weights:** `rtdetr-l.pt`\n",
                "- **Epochs:** `200`\n",
                "- **Optimizer:** `AdamW`\n",
                "- **Batch Size:** `12`"
            ]
        },
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "from ultralytics import RTDETR\n",
                "\n",
                "print('🎯 MEMULAI TRAINING RF-DETR / RT-DETR TRANSFORMER (200 EPOCHS)...')\n",
                "model_rfdetr = RTDETR('rtdetr-l.pt')\n",
                "\n",
                "results_rfdetr = model_rfdetr.train(\n",
                "    data='data.yaml',\n",
                "    epochs=200,\n",
                "    imgsz=640,\n",
                "    batch=12,\n",
                "    device=0,\n",
                "    workers=4,\n",
                "    optimizer='AdamW',\n",
                "    lr0=0.0001,\n",
                "    patience=50,\n",
                "    save=True,\n",
                "    project='raray_vision_runs',\n",
                "    name='rfdetr_200epochs'\n",
                ")\n",
                "\n",
                "print('\\n📊 VALIDASI RF-DETR:')\n",
                "metrics_rfdetr = model_rfdetr.val()\n",
                "print('Validation Results:', metrics_rfdetr)\n",
                "\n",
                "# Export ke ONNX\n",
                "model_rfdetr.export(format='onnx', dynamic=True, simplify=True)\n",
                "print('✓ RF-DETR weights & ONNX berhasil diekspor!')\n"
            ]
        },
        # LANGKAH 11: PACKAGING ZIP DENGAN TANGGAL & KETERANGAN SETTING
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 📦 Langkah 11: Pengemasan Bobot Model & Hasil Evaluasi ke File ZIP\n",
                "Tahap ini mengumpulkan file bobot terbaik (`best.pt`), bobot ONNX (`best.onnx`), kurva metrik, confusion matrix, dan `results.csv` ke dalam arsip ZIP yang rapi.\n",
                "Anda dapat menentukan **Tanggal Training** dan **Keterangan Setting / Hyperparameters** agar otomatis tercatat saat diunggah ke sistem Raray Vision."
            ]
        },
        {
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
                "KETERANGAN_SETTING = '200 Epochs, Imgsz 640, Batch 16, Optimizer AdamW, Tesla T4 GPU'\n",
                "\n",
                "print('=== PENGEMASAN ARSIP EVALUASI & BOBOT MODEL ===')\n",
                "# Cari run training terbaru di raray_vision_runs\n",
                "all_runs = sorted(glob.glob('raray_vision_runs/*'), key=os.path.getmtime, reverse=True)\n",
                "# Filter hanya direktori run\n",
                "valid_runs = [r for r in all_runs if os.path.isdir(r) and not r.endswith('.zip')]\n",
                "\n",
                "if not valid_runs:\n",
                "    print('❌ Belum ada folder hasil training di \"raray_vision_runs\". Silakan jalankan salah satu cell training di Langkah 8, 9, atau 10 terlebih dahulu.')\n",
                "else:\n",
                "    latest_run = valid_runs[0]\n",
                "    run_name = os.path.basename(latest_run)\n",
                "    print(f'📁 Direktori Training Terpilih: {latest_run}')\n",
                "    \n",
                "    # 1. Buat file metadata setting training\n",
                "    meta_info = {\n",
                "        'training_date': TANGGAL_TRAINING,\n",
                "        'training_settings': KETERANGAN_SETTING,\n",
                "        'run_name': run_name,\n",
                "        'created_at': datetime.now().isoformat()\n",
                "    }\n",
                "    meta_path = os.path.join(latest_run, 'training_meta.json')\n",
                "    with open(meta_path, 'w', encoding='utf-8') as mf:\n",
                "        json.dump(meta_info, mf, indent=2)\n",
                "    print(f'✓ Metadata setting tersimpan di: {meta_path}')\n",
                "    \n",
                "    # 2. Kemas Arsip Evaluasi (.zip) untuk diunggah ke Raray Vision\n",
                "    eval_zip_name = f'evaluasi_{run_name}_{TANGGAL_TRAINING}.zip'\n",
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
                "    bundle_zip_name = f'raray_vision_{run_name}_{TANGGAL_TRAINING}_bundle.zip'\n",
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
        },
        # LANGKAH 12: AUTO-DOWNLOAD KE BROWSER
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "### 📥 Langkah 12: Download Otomatis Bobot (`best.pt`) & Evaluasi (`.zip`) ke Komputer\n",
                "Menjalankan fungsi download Google Colab ke browser lokal Anda. Setelah terunduh, file siap diunggah ke web **Raray Vision** di menu **Model Management**."
            ]
        },
        {
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
                "    print('ℹ️ Script tidak dijalankan di Google Colab. File zip dan weights tersedia di direktori lokal.')\n"
            ]
        }
    ]

    return {
        "cells": colab_cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {
                "gpuType": "T4",
                "provenance": []
            },
            "kernelspec": {
                "display_name": "Python 3",
                "name": "python3"
            },
            "language_info": {
                "name": "python"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 0
    }


class DatasetUpdateRequest(BaseModel):
    name: str

class FeedbackRequest(BaseModel):
    feedback: str # "good" or "bad"
    notes: Optional[str] = None

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
    db: Session = Depends(get_db)
):
    """
    Submit user feedback on a prediction:
    'good' -> Accurate prediction, verified for auto-labeling.
    'bad' -> Inaccurate prediction, flagged for Label Studio human review queue.
    """
    record = db.query(MLPrediction).filter(MLPrediction.id == prediction_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Prediction record not found")

    status_val = payload.feedback.lower().strip()
    if status_val not in ["good", "bad", "pending"]:
        raise HTTPException(status_code=400, detail="Feedback must be 'good' or 'bad'")

    record.feedback_status = status_val
    if payload.notes:
        record.feedback_notes = payload.notes
    record.is_synced_to_ls = False # Reset sync flag so it gets picked up in next sync

    db.commit()
    db.refresh(record)

    return {
        "success": True,
        "prediction_id": record.id,
        "feedback_status": record.feedback_status,
        "feedback_notes": record.feedback_notes,
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
    db: Session = Depends(get_db)
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
        task_data = {
            "data": {
                "image": item.original_image_url,
                "prediction_id": item.id,
                "feedback_status": item.feedback_status,
                "feedback_notes": item.feedback_notes or ""
            }
        }

        # If it's good or auto_labeled, add pre-annotations
        if item.feedback_status in ["good", "auto_labeled"] and detections:
            ls_results = label_studio_service.format_detection_to_ls_annotation(detections)
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
        for item in items:
            item.is_synced_to_ls = True
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

        # Build Interactive .ipynb Notebook for Google Colab (YOLO-X, YOLO-26, RF-DETR, 200 Epochs, T4 GPU)
        colab_nb_dict = generate_colab_notebook_dict(
            folder_name=folder_name,
            yolo_yaml_url=yolo_yaml_url,
            tasks_url=tasks_url,
            coco_url=coco_url
        )
        colab_nb_bytes = json.dumps(colab_nb_dict, indent=2).encode("utf-8")
        colab_nb_s3_key = f"datasets/{folder_name}/raray_vision_colab_training.ipynb"
        colab_nb_url = _stable_dataset_url(s3_service.upload_bytes(colab_nb_bytes, colab_nb_s3_key, content_type="application/x-ipynb+json"))

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
    colab_nb_url = f"/api/v1/models/data/datasets/{dataset.id}/colab-notebook.ipynb"
    artifacts["colab_notebook_url"] = colab_nb_url

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
def get_dataset_colab_notebook(dataset_id: str, db: Session = Depends(get_db)):
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
        coco_url=coco_json_url
    )
    content = json.dumps(colab_nb, indent=2)
    filename = f"raray_vision_{dataset.folder}_colab.ipynb"
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
