#!/bin/sh
set -e

export PYTHONPATH=/workspace:$PYTHONPATH

echo "========================================================="
echo "Inicializando Sistema de Reservas de Aerolínea Regional"
echo "========================================================="
echo "1. Ejecutando creación automática de tablas y datos semilla..."

python scripts/seed_data.py

echo "========================================================="
echo "2. Base de datos y catálogo inicial listos."
echo "3. Iniciando servidor FastAPI en el puerto 8000..."
echo "========================================================="

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

