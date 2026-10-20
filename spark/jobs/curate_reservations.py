"""
Job PySpark del Parcial 2 (R4): limpia el histórico crudo y produce las dos tablas del
contrato de datos en Parquet.

  entrada  <raw>/flights.csv, <raw>/reservations.csv
  salida   <curated>/reservations_curated/month=YYYY-MM/*.parquet   (24 particiones)
           <curated>/route_month_metrics/*.parquet

Reglas de limpieza (exactas, ver parcial2-harness/contract/DATA.md):
  C1 route: quitar todo espacio en blanco y pasar a mayúsculas
  C2 status: quitar espacios en los extremos y pasar a mayúsculas
  C3 conservar solo status CONFIRMED o CANCELLED
  C4 descartar price_cents ausente o <= 0
  C5 descartar reservation_id duplicados conservando la primera aparición

Uso:
  EMR      spark-submit s3://BUCKET/jobs/curate_reservations.py --raw s3://BUCKET/raw --curated s3://BUCKET/curated
  local    spark-submit spark/jobs/curate_reservations.py --raw /data/raw --curated /data/lake/curated \
               --run-log /data/lake/_emr_local/runs.jsonl
"""
import argparse
import json
import os
from datetime import datetime, timezone

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

FLIGHTS_SCHEMA = StructType([StructField(c, StringType()) for c in
                             ["flight_id", "route", "flight_date", "capacity"]])
RESERVATIONS_SCHEMA = StructType([StructField(c, StringType()) for c in
                                  ["reservation_id", "flight_id", "fare_class", "price_cents", "status",
                                   "days_before_departure"]])

CURATED_COLUMNS = ["reservation_id", "flight_id", "route", "fare_class", "price_cents", "status", "month"]
METRIC_COLUMNS = ["route", "month", "seats_capacity", "seats_sold", "occupancy",
                  "revenue_cents", "bookings", "cancellations"]


def clean_flights(flights):
    return (flights
            # C1: sin espacios (incluye los interiores: "bog - mde" -> "BOG-MDE") y en mayúsculas
            .withColumn("route", F.upper(F.regexp_replace("route", r"\s+", "")))
            .withColumn("month", F.substring("flight_date", 1, 7))
            .withColumn("capacity", F.col("capacity").cast("bigint")))


def clean_reservations(res):
    # Se conserva el orden de lectura del archivo para que "la primera aparición" (C5) sea determinista.
    res = res.withColumn("_row", F.monotonically_increasing_id())
    res = res.withColumn("status", F.upper(F.regexp_replace("status", r"^\s+|\s+$", "")))      # C2
    res = res.filter(F.col("status").isin("CONFIRMED", "CANCELLED"))                          # C3
    price = F.col("price_cents").cast("double")
    res = (res.filter(price.isNotNull() & (price > 0))                                         # C4
              .withColumn("price_cents", price.cast("bigint")))
    first = Window.partitionBy("reservation_id").orderBy("_row")
    res = (res.withColumn("_rn", F.row_number().over(first))                                   # C5
              .filter(F.col("_rn") == 1)
              .drop("_rn", "_row"))
    return res


def build_detail(flights, res):
    return (res.join(flights.select("flight_id", "route", "month"), on="flight_id", how="inner")
               .select(*CURATED_COLUMNS))


def build_metrics(flights, detail):
    capacity = flights.groupBy("route", "month").agg(F.sum("capacity").alias("seats_capacity"))
    is_conf = F.col("status") == "CONFIRMED"
    sales = detail.groupBy("route", "month").agg(
        F.sum(F.when(is_conf, 1).otherwise(0)).cast("bigint").alias("seats_sold"),
        F.sum(F.when(is_conf, F.col("price_cents")).otherwise(0)).cast("bigint").alias("revenue_cents"),
        F.sum(F.when(F.col("status") == "CANCELLED", 1).otherwise(0)).cast("bigint").alias("cancellations"),
    )
    m = capacity.join(sales, on=["route", "month"], how="left").fillna(0)
    return (m.withColumn("bookings", F.col("seats_sold"))          # contrato: bookings = CONFIRMED
             .withColumn("occupancy", F.col("seats_sold").cast("double") / F.col("seats_capacity"))
             .select(*METRIC_COLUMNS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="prefijo con flights.csv y reservations.csv")
    ap.add_argument("--curated", required=True, help="prefijo de salida de las tablas curadas")
    ap.add_argument("--run-log", default=None, help="(solo local) jsonl donde se registra la corrida, como el historial de EMR")
    a = ap.parse_args()

    started = datetime.now(timezone.utc)
    spark = (SparkSession.builder.appName("airline-curate-reservations")
             .config("spark.sql.sources.partitionOverwriteMode", "static")
             .config("spark.sql.shuffle.partitions", "48")
             .getOrCreate())

    raw = a.raw.rstrip("/")
    out = a.curated.rstrip("/")
    flights = clean_flights(spark.read.csv(f"{raw}/flights.csv", header=True, schema=FLIGHTS_SCHEMA))
    res = clean_reservations(spark.read.csv(f"{raw}/reservations.csv", header=True, schema=RESERVATIONS_SCHEMA))

    detail = build_detail(flights, res).cache()
    # Un archivo por mes: Athena lee exactamente una partición en las consultas filtradas por mes (R6).
    (detail.repartition("month").write.mode("overwrite").partitionBy("month")
           .option("compression", "snappy").parquet(f"{out}/reservations_curated"))

    metrics = build_metrics(flights, detail)
    metrics.coalesce(1).write.mode("overwrite").option("compression", "snappy").parquet(f"{out}/route_month_metrics")

    rows = detail.count()
    months = detail.select("month").distinct().count()
    ended = datetime.now(timezone.utc)
    print(f"[curate] filas curadas={rows} meses={months} duración={(ended - started).total_seconds():.1f}s")

    if a.run_log:
        os.makedirs(os.path.dirname(a.run_log), exist_ok=True)
        with open(a.run_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": f"local-step-{int(started.timestamp())}", "state": "COMPLETED",
                                 "started_at": started.isoformat(), "ended_at": ended.isoformat(),
                                 "curated_rows": rows, "months": months}) + "\n")
    spark.stop()


if __name__ == "__main__":
    main()
