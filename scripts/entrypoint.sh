#!/bin/bash
set -e

# CPU Thread Optimization & Limit to prevent multi-core 100% saturation
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export UVICORN_WORKERS="${UVICORN_WORKERS:-1}"
export ENABLE_TIRE_COUNTER="${ENABLE_TIRE_COUNTER:-0}"

echo "=== [Raray Vision] Starting Optimized Backend ==="

TIRE_PID=""

# 1. Start Warehouse & Mining Tire Counter (Port 8001) only if explicitly enabled
if [ "$ENABLE_TIRE_COUNTER" = "1" ] || [ "$ENABLE_TIRE_COUNTER" = "true" ]; then
    echo "-> Starting Warehouse Tire Counter microservice on port 8001..."
    (cd /app/warehouse-tire-counter && python app.py) &
    TIRE_PID=$!
else
    echo "-> Warehouse Tire Counter microservice is DISABLED (ENABLE_TIRE_COUNTER=0) to save CPU."
fi

# Trap signals for graceful shutdown
cleanup() {
    echo "Shutting down services..."
    if [ -n "$TIRE_PID" ]; then
        kill -TERM "$TIRE_PID" 2>/dev/null || true
        wait "$TIRE_PID" 2>/dev/null || true
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM

# 2. Start Main Raray Vision FastAPI Backend (Port 5000)
echo "-> Starting Main Vision API on port 5000 with ${UVICORN_WORKERS} worker(s)..."
if [ -n "$TIRE_PID" ]; then
    cd /app && uvicorn backend.main:app --host 0.0.0.0 --port 5000 --workers "$UVICORN_WORKERS" --timeout-keep-alive 65 &
    MAIN_PID=$!
    wait -n "$MAIN_PID" "$TIRE_PID"
    cleanup
else
    cd /app && exec uvicorn backend.main:app --host 0.0.0.0 --port 5000 --workers "$UVICORN_WORKERS" --timeout-keep-alive 65
fi

