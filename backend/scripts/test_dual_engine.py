import os
import sys
import cv2
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.services.ml_service import (
    get_global_engine_mode,
    set_global_engine_mode,
    get_face_app,
    get_spoof_session,
    benchmark_engines_comparison
)

print(f"[*] Initial Global Engine: {get_global_engine_mode()}")

# Test switching
set_global_engine_mode('v2')
print(f"[*] Switched to: {get_global_engine_mode()}")

# Check if there is an image to test with in assets
sample_img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "assets", "img2.jpeg"))
if os.path.exists(sample_img_path):
    print(f"[*] Loading sample face image: {sample_img_path}")
    test_img = cv2.imread(sample_img_path)
else:
    test_img = np.zeros((480, 640, 3), dtype=np.uint8)

# Run benchmark
res = benchmark_engines_comparison(test_img)
print(f"[*] Benchmark Result Status: {res.get('status')}")
print(f"[*] V1 Total Latency: {res.get('v1_standard', {}).get('data', {}).get('total_latency_ms')} ms")
print(f"[*] V2 Total Latency: {res.get('v2_cpu_turbo', {}).get('data', {}).get('total_latency_ms')} ms")
print(f"[*] Speedup Ratio: {res.get('comparison', {}).get('speedup_ratio')}")
print(f"[*] Embedding Similarity: {res.get('comparison', {}).get('embedding_similarity')}")

set_global_engine_mode('v1')
print("[OK] Dual-Engine verification finished successfully!")
