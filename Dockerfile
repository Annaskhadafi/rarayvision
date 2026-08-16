FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH="/app:/app/backend:/app/warehouse-tire-counter"
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

# Copy application code
COPY . .

# Ensure entrypoint script is executable
RUN chmod +x scripts/entrypoint.sh

# Expose Main Vision API (5000) and Warehouse Tire Counter (8001)
EXPOSE 5000 8001

CMD ["/bin/bash", "scripts/entrypoint.sh"]

