FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH="/app:/app/warehouse-tire-counter"
ENV PYTHONUNBUFFERED=1

# Install system dependencies for OpenCV, Video decoding and networking
RUN apt-get update && apt-get install -y --no-install-recommends \
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

RUN pip install --no-cache-dir --upgrade pip setuptools wheel numpy

# Install CPU-only PyTorch for fast inference & smaller container footprint
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy full application code
COPY . .

EXPOSE 8001

CMD ["python", "warehouse-tire-counter/app.py"]
