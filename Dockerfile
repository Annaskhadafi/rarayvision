FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH="/app:/app/backend"
ENV PYTHONUNBUFFERED=1
# Persistent Cache Directory for Models (HuggingFace, FastEmbed, Torch)
ENV HF_HOME=/app/cache/huggingface
ENV FASTEMBED_CACHE_PATH=/app/cache/fastembed
ENV TORCH_HOME=/app/cache/torch
ENV TIMESFM_LOCAL_FILES_ONLY=1

# Install system dependencies for OpenCV, Tesseract, PyTorch, FFMPEG, PaddleOCR, and ONNX
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install core build tools first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel cython numpy

# Install CPU-only PyTorch first to save disk space and RAM during Docker build
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download FastEmbed ONNX & faster-whisper models to image layer for 100% offline zero-latency startup
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; TextEmbedding('BAAI/bge-small-en-v1.5'); TextCrossEncoder('jinaai/jina-reranker-v1-tiny-en')" || true
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')" || true
# Download the TimesFM checkpoint into the image so the first forecast is offline and deterministic.
RUN python -c "import timesfm; cls=getattr(timesfm, 'TimesFM_2p5_200M_torch', None) or __import__('timesfm.timesfm_2p5.timesfm_2p5_torch', fromlist=['TimesFM_2p5_200M_torch']).TimesFM_2p5_200M_torch; cls.from_pretrained('google/timesfm-2.5-200m-pytorch', torch_compile=False)"

# Backup pre-downloaded model cache to /opt/models_cache so it can be restored if /app/cache is bind-mounted
RUN mkdir -p /opt/models_cache && cp -r /app/cache/* /opt/models_cache/ 2>/dev/null || true

# Copy application code
COPY . .

# Keep the checked-in Fire model outside the runtime volume. docker-compose mounts
# /app/backend/ml_models, which otherwise hides files copied into the image.
RUN mkdir -p /opt/rarayvision-fire-model/Fire /opt/rarayvision-fire-model/model \
    && cp backend/ml_models/Fire/best.pt /opt/rarayvision-fire-model/Fire/best.pt \
    && cp backend/model/best.onnx /opt/rarayvision-fire-model/model/best.onnx

# Ensure entrypoint script is executable
RUN chmod +x scripts/entrypoint.sh

# Expose Main Vision API (5000)
EXPOSE 5000

CMD ["/bin/bash", "scripts/entrypoint.sh"]
