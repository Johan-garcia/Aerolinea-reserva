#!/bin/sh
set -e

export PYTHONPATH=/workspace:$PYTHONPATH

echo "========================================================="
echo "Inicializando Sistema de Reservas de Aerolínea Regional"
echo "========================================================="
echo "1. Creando tablas y datos semilla (Parcial 1)..."
python scripts/seed_data.py

echo "2. Creando vuelos de demostración (Parcial 2)..."
python scripts/seed_demo_flights.py

echo "3. Iniciando FastAPI en el puerto 8000 con ${UVICORN_WORKERS:-2} workers (motor analítico: ${ANALYTICS_ENGINE:-duckdb})..."
echo "========================================================="

if [ "${DEV_RELOAD:-0}" = "1" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-2}" --no-access-log
