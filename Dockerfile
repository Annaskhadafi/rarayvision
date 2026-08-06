FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by OpenCV, Tesseract OCR Engine, PyTorch, and ONNX
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
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install with CPU PyTorch index fallback
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# Copy application code
COPY . .

EXPOSE 5000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "5000"]
