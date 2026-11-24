#!/usr/bin/env bash
# Preparación ÚNICA de la parte AWS del Parcial 3 (se puede repetir sin romper nada).
#
#   BUCKET=airline-wilches-garcia-24306 bash aws/p3/setup.sh
#
#   1. Workgroup de Athena "airline-p3" con límite de 1 GB escaneado por consulta (R10) y carpeta de resultados.
#   2. Base de datos airline_star en el Glue Data Catalog (las tablas las crea el worker en cada refresco).
#   3. Agrega las variables del Parcial 3 al .env del EC2 (sin credenciales).
set -euo pipefail

: "${BUCKET:?Defina BUCKET=nombre-del-bucket (el mismo del Parcial 2)}"
REGION="${AWS_REGION:-us-east-1}"
WG="${STAR_WORKGROUP:-airline-p3}"
DB="${STAR_DATABASE:-airline_star}"
OUT="s3://${BUCKET}/athena-results/"
CUTOFF=1000000000   # 1 GB decimal: el harness exige <= 1.000.000.000 B (1 GiB = 1.073.741.824 se pasaría)
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "1/3 Workgroup $WG (límite por consulta: $CUTOFF B, resultados en $OUT)"
CONF="ResultConfiguration={OutputLocation=$OUT},EnforceWorkGroupConfiguration=true,PublishCloudWatchMetricsEnabled=false,BytesScannedCutoffPerQuery=$CUTOFF"
if aws athena get-work-group --region "$REGION" --work-group "$WG" >/dev/null 2>&1; then
  aws athena update-work-group --region "$REGION" --work-group "$WG" \
    --configuration-updates "ResultConfigurationUpdates={OutputLocation=$OUT},EnforceWorkGroupConfiguration=true,BytesScannedCutoffPerQuery=$CUTOFF"
else
  aws athena create-work-group --region "$REGION" --name "$WG" --configuration "$CONF" \
    --description "Parcial 3: estrella de eventos (limite 1 GB por consulta)"
fi
aws athena get-work-group --region "$REGION" --work-group "$WG" \
  --query 'WorkGroup.Configuration.{limite_bytes:BytesScannedCutoffPerQuery,salida:ResultConfiguration.OutputLocation}' --output table

echo "2/3 Base de datos $DB"
QID=$(aws athena start-query-execution --region "$REGION" --work-group "$WG" \
      --query-string "CREATE DATABASE IF NOT EXISTS $DB" --query QueryExecutionId --output text)
until s=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$QID" \
          --query QueryExecution.Status.State --output text) && [[ "$s" =~ SUCCEEDED|FAILED|CANCELLED ]]; do sleep 1; done
echo "   $s"

echo "3/3 Variables del Parcial 3 en $ROOT/.env"
touch "$ROOT/.env"
set_env() { grep -q "^$1=" "$ROOT/.env" && sed -i.bak "s#^$1=.*#$1=$2#" "$ROOT/.env" || echo "$1=$2" >> "$ROOT/.env"; }
set_env KINESIS_STREAM "${KINESIS_STREAM:-airline-events}"
set_env RAW_EVENTS_URI "s3://${BUCKET}/raw/events/"
set_env STAR_URI "s3://${BUCKET}/star/"
set_env STAR_DATABASE "$DB"
set_env STAR_WORKGROUP "$WG"
set_env ATHENA_OUTPUT "$OUT"
rm -f "$ROOT/.env.bak"
grep -E "KINESIS|RAW_EVENTS|STAR_|ATHENA_OUTPUT" "$ROOT/.env"

[ -f "$ROOT/ref/routes_ref.csv" ] || echo "AVISO: falta ref/ (bash aws/p3/generate_ref.sh <SEMILLA>)"
echo "Listo. Siguiente: bash aws/p3/stream.sh create && sudo docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build"
