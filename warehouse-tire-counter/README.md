# Warehouse Tire Object Counter

Sistem penghitung objek otomatis (*Object Counter*) untuk stok gudang dan konveyor ban (*tire stock management*) berbasis **Ultralytics YOLO** & **ByteTrack**.

---

## 🌟 Fitur Utama
- **Line In/Out Counting**: Menghitung ban masuk/keluar saat melintasi garis virtual (konveyor / pintu gudang / forklift dock).
- **Anti Double-Count**: Menggunakan Multi-Object Tracking (ByteTrack) untuk memastikan setiap ban hanya dihitung sekali.
- **Dukungan Model Gratis**:
  - **YOLO-World (Zero-Shot)**: Langsung mendeteksi kata kunci `"tire"`, `"car tire"`, `"truck tire"` tanpa perlu train ulang.
  - **Pretrained Roboflow / Custom `.pt`**: Kompatibel langsung dengan file weight YOLOv8/YOLOv11 apa pun.
- **Visual HUD & Video Export**: Menampilkan overlay hitungan real-time dan menyimpan rekaman beranotasi.
- **Export Riwayat (JSON)**: Mencatat timestamp, track ID, arah gerak, dan total stok.

---

## 🚀 Panduan Menjalankan Demo

### 1. Test dengan Video Sampel Buatan (Konveyor Otomatis)
```bash
cd "d:/[01] PROJECT/Raray VIsion/warehouse-tire-counter"
python demo_counter.py --source samples/conveyor_sample.mp4 --no-display
```

### 2. Menggunakan Model YOLO-World (Zero-Shot Deteksi Ban)
Model akan diunduh otomatis sekali oleh Ultralytics:
```bash
python demo_counter.py --model yolov8s-worldv2.pt --source "path/to/cctv_video.mp4"
```

### 3. Menggunakan Live Webcam / Kamera USB
```bash
python demo_counter.py --source 0
```

### 4. Menggunakan CCTV IP / RTSP Stream Gudang
```bash
python demo_counter.py --source "rtsp://admin:password@192.168.1.100:554/live" --line-y 300
```

---

## 📦 Opsi Model Gratis Tambahan

1. **YOLO-World v2 (`yolov8s-worldv2.pt`)**:
   Opsi termudah & gratis bawaan Ultralytics untuk deteksi open-vocabulary.
2. **Roboflow Universe (Public Datasets & Weights)**:
   - Cari di [Roboflow Universe Tire Detection](https://universe.roboflow.com/search?q=tire+detection)
   - Download model berformat `YOLOv8 PyTorch (.pt)` dan letakkan di folder ini:
     ```bash
     python demo_counter.py --model best_tire_model.pt --source cctv.mp4
     ```
