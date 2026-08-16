#!/bin/bash
# =============================================================
# download_models.sh
# Download ML model files that are NOT stored in git.
# Run this once after cloning the repo on your server.
# =============================================================

set -e

MODELS_DIR="backend/ml_models"
mkdir -p "$MODELS_DIR"

echo "=== Downloading ML Models ==="

# --- Anti-Spoofing: MiniFASNetV2 ---
MINIFAS_PATH="$MODELS_DIR/MiniFASNetV2.onnx"
if [ ! -f "$MINIFAS_PATH" ]; then
  echo "Downloading MiniFASNetV2.onnx..."
  # Option A: From your S3 / Object Storage (recommended)
  # curl -L "https://your-s3-bucket.s3.region.amazonaws.com/models/MiniFASNetV2.onnx" -o "$MINIFAS_PATH"

  # Option B: From HuggingFace / public mirror
  # curl -L "https://huggingface.co/your-org/models/resolve/main/MiniFASNetV2.onnx" -o "$MINIFAS_PATH"

  echo "  ⚠️  MiniFASNetV2.onnx - Please configure a download URL above."
else
  echo "  ✅ MiniFASNetV2.onnx already exists, skipping."
fi

# --- Emotion Detection: emotion-ferplus-8 ---
EMOTION_PATH="$MODELS_DIR/emotion-ferplus-8.onnx"
if [ ! -f "$EMOTION_PATH" ]; then
  echo "Downloading emotion-ferplus-8.onnx (~33MB)..."
  # Official ONNX Model Zoo (public):
  curl -L "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx" \
    -o "$EMOTION_PATH" \
    --retry 3 --retry-delay 2 \
    || echo "  ⚠️  Download failed. Please download manually from: https://github.com/onnx/models"
  echo "  ✅ emotion-ferplus-8.onnx downloaded."
else
  echo "  ✅ emotion-ferplus-8.onnx already exists, skipping."
fi

echo ""
echo "=== All models ready ==="
