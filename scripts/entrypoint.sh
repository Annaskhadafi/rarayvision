#!/bin/bash
set -e

echo "=== [Raray Vision] Starting Dual Microservices in Single Container ==="

# 1. Start Warehouse & Mining Tire Counter (Port 8001) in background
echo "-> Starting Warehouse Tire Counter microservice on port 8001..."
(cd /app/warehouse-tire-counter && python app.py) &
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
cd /app && uvicorn backend.main:app --host 0.0.0.0 --port 5000 &
MAIN_PID=$!

# Wait for any process to exit
wait -n "$MAIN_PID" "$TIRE_PID"
cleanup

