#!/bin/bash
set -e

echo "=== [Raray Vision] Starting Services ==="

# 1. Start Warehouse & Mining Tire Counter Microservice (Port 8001) in background
echo "-> Starting Warehouse Tire Counter on port 8001..."
python warehouse-tire-counter/app.py &
TIRE_PID=$!

# Trap signals for graceful shutdown of both services
cleanup() {
    echo "Shutting down services..."
    kill -TERM "$TIRE_PID" 2>/dev/null || true
    wait "$TIRE_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# 2. Start Main Raray Vision FastAPI Backend (Port 5000) in foreground
echo "-> Starting Main Vision API on port 5000..."
uvicorn backend.main:app --host 0.0.0.0 --port 5000 &
MAIN_PID=$!

# Wait for any process to exit
wait -n "$MAIN_PID" "$TIRE_PID"
cleanup
