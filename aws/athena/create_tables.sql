-- Glue Data Catalog + Athena (R5, R6). Ejecutar en la consola de Athena, una sentencia a la vez,
-- reemplazando YOUR-BUCKET. No requiere crawler: las tablas se declaran con el contrato exacto.

CREATE DATABASE IF NOT EXISTS airline_analytics;

-- Tabla 1: detalle curado, particionado por mes. Partition projection: Athena calcula las 24
-- particiones a partir del rango, sin MSCK REPAIR ni crawler, y solo lee month=X cuando se filtra.
CREATE EXTERNAL TABLE IF NOT EXISTS airline_analytics.reservations_curated (
  reservation_id string,
  flight_id      string,
  route          string,
  fare_class     string,
  price_cents    bigint,
  status         string
)
PARTITIONED BY (month string)
STORED AS PARQUET
LOCATION 's3://YOUR-BUCKET/curated/reservations_curated/'
TBLPROPERTIES (
  'classification'            = 'parquet',
  'projection.enabled'        = 'true',
  'projection.month.type'     = 'date',
  'projection.month.format'   = 'yyyy-MM',
  'projection.month.range'    = '2023-01,2024-12',
  'projection.month.interval' = '1',
  'projection.month.interval.unit' = 'MONTHS',
  'storage.location.template' = 's3://YOUR-BUCKET/curated/reservations_curated/month=${month}/'
);

-- Tabla 2: métricas por ruta y mes (pequeña, sin particionar).
CREATE EXTERNAL TABLE IF NOT EXISTS airline_analytics.route_month_metrics (
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
LOCATION 's3://YOUR-BUCKET/curated/route_month_metrics/'
TBLPROPERTIES ('classification' = 'parquet');

-- Verificación rápida
SELECT count(*) FROM airline_analytics.reservations_curated;                    -- = filas curadas
SELECT * FROM airline_analytics.route_month_metrics ORDER BY occupancy DESC LIMIT 10;
