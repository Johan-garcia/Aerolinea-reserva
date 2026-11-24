#!/usr/bin/env bash
# Crea, borra o muestra el stream de Kinesis del Parcial 3 (R11: aprovisionado, 1 shard, 24 h, sin EFO).
#
#   bash aws/p3/stream.sh create     # al empezar a trabajar / antes del harness
#   bash aws/p3/stream.sh delete     # al terminar: un shard se cobra por cada hora que EXISTE
#   bash aws/p3/stream.sh status
#
# El worker sobrevive a que el stream no exista (reintenta cada 30 s) y, cuando se vuelve a crear,
# detecta que es otro stream (fecha de creación distinta) y empieza a leer desde TRIM_HORIZON.
set -euo pipefail
STREAM="${KINESIS_STREAM:-airline-events}"
REGION="${AWS_REGION:-us-east-1}"

case "${1:-status}" in
  create)
    if aws kinesis describe-stream-summary --region "$REGION" --stream-name "$STREAM" >/dev/null 2>&1; then
      echo "El stream $STREAM ya existe"
    else
      aws kinesis create-stream --region "$REGION" --stream-name "$STREAM" \
        --shard-count 1 --stream-mode-details StreamMode=PROVISIONED
      echo "Esperando a que $STREAM quede ACTIVE..."
      aws kinesis wait stream-exists --region "$REGION" --stream-name "$STREAM"
    fi
    ;;
  delete)
    aws kinesis delete-stream --region "$REGION" --stream-name "$STREAM" --enforce-consumer-deletion \
      && echo "Borrado $STREAM (deja de cobrar en unos segundos)" || echo "No existía $STREAM"
    exit 0
    ;;
  status) ;;
  *) echo "uso: $0 create|delete|status" >&2; exit 2 ;;
esac

aws kinesis describe-stream-summary --region "$REGION" --stream-name "$STREAM" \
  --query 'StreamDescriptionSummary.{estado:StreamStatus,modo:StreamModeDetails.StreamMode,shards:OpenShardCount,retencion_h:RetentionPeriodHours,consumidores_efo:ConsumerCount}' \
  --output table 2>/dev/null || echo "El stream $STREAM no existe (no está cobrando)."
