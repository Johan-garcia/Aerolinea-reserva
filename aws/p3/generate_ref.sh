#!/usr/bin/env bash
# Genera los archivos de referencia de las dimensiones con la semilla del equipo (sección 4.1):
#   ref/routes_ref.csv, ref/route_category_history.csv, ref/holidays_ref.csv
#
#   bash aws/p3/generate_ref.sh <SEMILLA>
#
# Usa Python local si tiene numpy y pandas; si no, un contenedor python:3.11-slim.
# Los archivos se versionan en git (no son secretos) y el worker los monta en /workspace/ref.
set -euo pipefail
SEED="${1:?uso: $0 <SEMILLA>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
H="$ROOT/parcial3-harness-estudiantes"

if python3 -c "import numpy, pandas" 2>/dev/null; then
  (cd "$H" && python3 -m airline_data.generate_p3 --seed "$SEED" --out "$ROOT/ref")
else
  SUDO=""; docker info >/dev/null 2>&1 || SUDO="sudo"   # en el EC2 docker requiere sudo; en el Mac no
  $SUDO docker run --rm -v "$H:/harness:ro" -v "$ROOT/ref:/ref" -w /harness python:3.11-slim \
    sh -c "pip install --quiet --no-cache-dir numpy pandas && python -m airline_data.generate_p3 --seed $SEED --out /ref"
fi
echo "$SEED" > "$ROOT/ref/SEED"
wc -l "$ROOT"/ref/*.csv
