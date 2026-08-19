import os
import sys
import time
import cv2
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from insightface.app import FaceAnalysis

sample_img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "assets", "img2.jpeg"))
img = cv2.imread(sample_img_path)

# Test 1: Full 5 modules in buffalo_s
app_full = FaceAnalysis(name='buffalo_s', providers=['CPUExecutionProvider'])
app_full.prepare(ctx_id=0, det_size=(320, 320))
# Warmup
app_full.get(img)

t0 = time.perf_counter()
faces1 = app_full.get(img)
t1 = (time.perf_counter() - t0) * 1000
print(f"[*] Buffalo_S (All 5 modules): {t1:.2f} ms")

# Test 2: Only Detection + Recognition in buffalo_s
app_fast = FaceAnalysis(name='buffalo_s', allowed_modules=['detection', 'recognition'], providers=['CPUExecutionProvider'])
app_fast.prepare(ctx_id=0, det_size=(320, 320))
# Warmup
app_fast.get(img)

t0 = time.perf_counter()
faces2 = app_fast.get(img)
t2 = (time.perf_counter() - t0) * 1000
print(f"[*] Buffalo_S (detection + recognition ONLY): {t2:.2f} ms")
print(f"[*] Faces detected: {len(faces2)}, Embedding size: {len(faces2[0].embedding) if faces2 else 0}")
print(f"[*] Turbo Speedup: {t1 / max(t2, 0.1):.2f}x faster!")
