FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH="/app:/app/backend"
ENV PYTHONUNBUFFERED=1
# Persistent Cache Directory for Models (HuggingFace, FastEmbed, Torch)
ENV HF_HOME=/app/cache/huggingface
ENV FASTEMBED_CACHE_PATH=/app/cache/fastembed
ENV TORCH_HOME=/app/cache/torch

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
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; TextEmbedding('BAAI/bge-small-en-v1.5'); TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2')" || true
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')" || true

# Copy application code
COPY . .

# Ensure entrypoint script is executable
RUN chmod +x scripts/entrypoint.sh

# Expose Main Vision API (5000)
EXPOSE 5000

CMD ["/bin/bash", "scripts/entrypoint.sh"]
