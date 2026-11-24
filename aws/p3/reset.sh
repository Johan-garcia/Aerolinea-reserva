#!/usr/bin/env bash
# Arranque LIMPIO antes de la corrida oficial del harness (sustentación).
#
#   BUCKET=airline-wilches-garcia-24306 bash aws/p3/reset.sh
#
# Por qué: el harness reinyecta su replay con event_id fijos (rp-<semilla>-s0, ...) pero el profesor usa
# OTROS datos (probe_salt secreto). Si la landing zone conserva nuestros replays de práctica, esos eventos
# viejos con los mismos event_id se mezclarían con los del profesor y R7/R8/R9 fallarían.
# (Probado en local: 49/70 sin limpiar, 70/70 limpiando.)
#
# Orden importante: se detiene el worker ANTES de borrar el stream, para que no vuelva a escribir en la
# landing zone registros del stream viejo.
set -euo pipefail
: "${BUCKET:?Defina BUCKET=nombre-del-bucket}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
DC="sudo docker compose -f docker-compose.yml -f docker-compose.aws.yml"

echo "1/5 Deteniendo el worker"
$DC stop worker

echo "2/5 Borrando el stream (y su contenido de las últimas 24 h)"
bash aws/p3/stream.sh delete
aws kinesis wait stream-not-exists --stream-name "${KINESIS_STREAM:-airline-events}" --region "${AWS_REGION:-us-east-1}" || true

echo "3/5 Vaciando la landing zone y la estrella en S3"
aws s3 rm "s3://${BUCKET}/raw/events/" --recursive --quiet || true
aws s3 rm "s3://${BUCKET}/star/" --recursive --quiet || true

echo "4/5 Borrando el estado del worker (checkpoint + caché del raw)"
$DC rm -f worker
sudo docker volume rm "$(basename "$ROOT")_worker_state" 2>/dev/null || true

echo "5/5 Creando el stream de nuevo y encendiendo el worker"
bash aws/p3/stream.sh create
$DC up -d worker
sleep 5
$DC exec -T worker curl -fsS http://localhost:8001/health && echo
