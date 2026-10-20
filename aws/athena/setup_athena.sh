#!/usr/bin/env bash
# Registra las dos tablas del contrato en el Glue Data Catalog a través de Athena (R5) y hace una
# verificación rápida (R6). Es la versión por consola de create_tables.sql, sin copiar y pegar.
#
#   BUCKET=airline-wilches-garcia bash aws/athena/setup_athena.sh
#
# Requiere: el job de EMR ya corrió (existen s3://BUCKET/curated/...) y credenciales del Learner Lab.
set -euo pipefail

: "${BUCKET:?Defina BUCKET=nombre-del-bucket}"
REGION="${AWS_REGION:-us-east-1}"
WG="${ATHENA_WORKGROUP:-primary}"
OUT="s3://${BUCKET}/athena-results/"
DB="airline_analytics"

run_q() {
  local sql="$1" qid state
  qid=$(aws athena start-query-execution --region "$REGION" --work-group "$WG" \
        --query-string "$sql" --result-configuration "OutputLocation=$OUT" \
        --query QueryExecutionId --output text)
  while true; do
    state=$(aws athena get-query-execution --region "$REGION" --query-execution-id "$qid" \
            --query QueryExecution.Status.State --output text)
    case "$state" in
      SUCCEEDED) break ;;
      FAILED|CANCELLED)
        aws athena get-query-execution --region "$REGION" --query-execution-id "$qid" \
          --query QueryExecution.Status.StateChangeReason --output text >&2
        return 1 ;;
    esac
    sleep 1
  done
  echo "$qid"
}

show() {  # imprime el resultado de una consulta como tabla
  local qid
  qid=$(run_q "$1")
  aws athena get-query-results --region "$REGION" --query-execution-id "$qid" \
    --query 'ResultSet.Rows[].Data[].VarCharValue' --output text
}

echo "1/4 Base de datos $DB en Glue"
run_q "CREATE DATABASE IF NOT EXISTS $DB" >/dev/null

echo "2/4 Tabla reservations_curated (Parquet, partición month con partition projection)"
run_q "DROP TABLE IF EXISTS $DB.reservations_curated" >/dev/null
run_q "CREATE EXTERNAL TABLE $DB.reservations_curated (
  reservation_id string,
  flight_id      string,
  route          string,
  fare_class     string,
  price_cents    bigint,
  status         string
)
PARTITIONED BY (month string)
STORED AS PARQUET
LOCATION 's3://${BUCKET}/curated/reservations_curated/'
TBLPROPERTIES (
  'classification'                 = 'parquet',
  'projection.enabled'             = 'true',
  'projection.month.type'          = 'date',
  'projection.month.format'        = 'yyyy-MM',
  'projection.month.range'         = '2023-01,2024-12',
  'projection.month.interval'      = '1',
  'projection.month.interval.unit' = 'MONTHS',
  'storage.location.template'      = 's3://${BUCKET}/curated/reservations_curated/month=\${month}/'
)" >/dev/null

echo "3/4 Tabla route_month_metrics (Parquet, sin particionar: 288 filas)"
run_q "DROP TABLE IF EXISTS $DB.route_month_metrics" >/dev/null
run_q "CREATE EXTERNAL TABLE $DB.route_month_metrics (
  route          string,
  month          string,
  seats_capacity bigint,
  seats_sold     bigint,
  occupancy      double,
  revenue_cents  bigint,
  bookings       bigint,
  cancellations  bigint
)
STORED AS PARQUET
LOCATION 's3://${BUCKET}/curated/route_month_metrics/'
TBLPROPERTIES ('classification' = 'parquet')" >/dev/null

echo "4/4 Verificación"
echo "  Filas curadas (semilla 24306 => 1977131):"
show "SELECT count(*) FROM $DB.reservations_curated"
echo "  Filas de métricas (12 rutas x 24 meses => 288):"
show "SELECT count(*) FROM $DB.route_month_metrics"
echo "  Top 3 rutas por ocupación:"
show "SELECT route, round(CAST(sum(seats_sold) AS DOUBLE)/sum(seats_capacity), 4) FROM $DB.route_month_metrics GROUP BY route ORDER BY 2 DESC LIMIT 3"
qid=$(run_q "SELECT count(*), sum(price_cents) FROM $DB.reservations_curated WHERE month='2024-01'")
echo "  Bytes escaneados por una consulta de un mes (debe ser < ~1,6 MB):"
aws athena get-query-execution --region "$REGION" --query-execution-id "$qid" \
  --query QueryExecution.Statistics.DataScannedInBytes --output text
