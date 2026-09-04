#!/bin/bash
set -e

# CPU Thread Optimization & Limit to prevent multi-core 100% saturation
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export UVICORN_WORKERS="${UVICORN_WORKERS:-1}"

echo "=== [Raray Vision] Starting Optimized Backend ==="

# Ensure persistent cache and upload directories exist
mkdir -p /app/cache/huggingface /app/cache/fastembed /app/cache/torch /app/backend/uploads
chmod -R 777 /app/cache /app/backend/uploads 2>/dev/null || true

# Trap signals for graceful shutdown
cleanup() {
    echo "Shutting down services..."
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start Main Raray Vision FastAPI Backend (Port 5000)
echo "-> Starting Main Vision API on port 5000 with ${UVICORN_WORKERS} worker(s)..."
cd /app && exec uvicorn backend.main:app --host 0.0.0.0 --port 5000 --workers "$UVICORN_WORKERS" --timeout-keep-alive 65


