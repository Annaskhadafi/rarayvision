FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH="/app:/app/backend"
ENV PYTHONUNBUFFERED=1

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

# Pre-download FastEmbed ONNX embedding & cross-encoder reranker models to image layer for zero-latency startup
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; TextEmbedding('BAAI/bge-small-en-v1.5'); TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2')" || true

# Copy application code
COPY . .

# Ensure entrypoint script is executable
RUN chmod +x scripts/entrypoint.sh

# Expose Main Vision API (5000)
EXPOSE 5000

CMD ["/bin/bash", "scripts/entrypoint.sh"]

