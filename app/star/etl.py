"""
ETL landing zone -> esquema estrella (R5-R10). Corre dentro del worker, en micro-lotes.

  1. Sincroniza la landing zone con una caché local (los objetos son inmutables: solo se bajan los nuevos).
  2. Decodifica cada registro (JSON por línea, gzip) a una tabla `raw_events` en DuckDB.
  3. Construye dimensiones y hechos con SQL (app/star/sql.py): dedup por event_id, fecha por event_ts,
     SCD2 con as-of join, claves sustitutas.
  4. Escribe Parquet en una carpeta NUEVA por corrida (star/<tabla>/build=<id>/) y repunta las tablas del
     Glue Data Catalog con DDL de Athena (DDL no se factura). fact_search queda particionada por mes y
     sus particiones se registran con ALTER TABLE ADD PARTITION.
  5. Borra las corridas viejas (conserva la anterior por si alguna consulta la estaba leyendo).

Idempotente: es una reconstrucción completa desde la landing zone; correrla dos veces con los mismos
objetos produce exactamente las mismas tablas (nunca duplica filas).
"""
import gzip
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone

import duckdb

from app.worker.lake import Lake

from . import sql as Q

log = logging.getLogger("star.etl")

RAW_COLUMNS = {
    "arrival_order": "BIGINT", "event_id": "VARCHAR", "event_type": "VARCHAR", "event_ts": "VARCHAR",
    "schema_version": "INTEGER", "session_id": "VARCHAR", "origin": "VARCHAR", "destination": "VARCHAR",
    "travel_date": "VARCHAR", "results_count": "INTEGER", "reservation_id": "VARCHAR", "flight_id": "VARCHAR",
    "route": "VARCHAR", "flight_date": "VARCHAR", "fare_class": "VARCHAR", "price_cents": "BIGINT",
}
KEEP_BUILDS = 2

_HIVE_TYPES = {"INTEGER": "int", "BIGINT": "bigint", "BOOLEAN": "boolean", "DATE": "date", "VARCHAR": "string",
               "DOUBLE": "double", "SMALLINT": "smallint", "TINYINT": "tinyint"}


# --------------------------------------------------------------------------- lectura de la landing
def _iter_json(text: str):
    """Objetos JSON de un texto: uno por línea o concatenados. Lo que no se pueda leer se salta."""
    dec = json.JSONDecoder()
    for line in text.splitlines():
        i, n = 0, len(line)
        while i < n:
            while i < n and line[i] in " \t\r":
                i += 1
            if i >= n:
                break
            try:
                obj, j = dec.raw_decode(line, i)
            except ValueError:
                break
            yield obj
            i = j


def _as_int(v):
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def sync_raw(raw: Lake, cache_dir: str) -> list[str]:
    """Devuelve rutas locales de todos los objetos de la landing, en orden de llegada."""
    if not raw.is_s3:
        return [os.path.join(raw.root, k) for k in raw.list()]
    os.makedirs(cache_dir, exist_ok=True)
    paths = []
    keys = raw.list()
    # Si alguien vació la landing zone (scripts/p3/reset_lake.sh), la caché también lo olvida.
    vivos = {k.replace("/", "__") for k in keys}
    for f in os.listdir(cache_dir):
        if f not in vivos:
            os.remove(os.path.join(cache_dir, f))
    for key in keys:
        local = os.path.join(cache_dir, key.replace("/", "__"))
        if not os.path.exists(local):
            tmp = local + ".part"
            with open(tmp, "wb") as fh:
                fh.write(raw.get(key))
            os.replace(tmp, local)
        paths.append(local)
    return paths


def write_ndjson(paths: list[str], out_path: str) -> dict:
    stats = {"objects": len(paths), "records": 0, "unreadable": 0}
    order = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for p in paths:
            with open(p, "rb") as fh:
                body = fh.read()
            if body[:2] == b"\x1f\x8b":
                try:
                    body = gzip.decompress(body)
                except OSError:
                    stats["unreadable"] += 1
                    continue
            for ev in _iter_json(body.decode("utf-8", errors="replace")):
                if not isinstance(ev, dict):
                    stats["unreadable"] += 1
                    continue
                order += 1
                row = {k: ev.get(k) for k in RAW_COLUMNS if k != "arrival_order"}
                row["arrival_order"] = order
                for k in ("schema_version", "results_count", "price_cents"):
                    row[k] = _as_int(row[k])
                for k in RAW_COLUMNS:
                    if RAW_COLUMNS[k] == "VARCHAR" and row[k] is not None and not isinstance(row[k], str):
                        row[k] = str(row[k])
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats["records"] = order
    return stats


# --------------------------------------------------------------------------- construcción
def build(con: duckdb.DuckDBPyConnection, ndjson: str, ref_dir: str):
    cols = "{" + ", ".join(f"'{k}': '{v}'" for k, v in RAW_COLUMNS.items()) + "}"
    con.execute(f"CREATE OR REPLACE TABLE raw_events AS SELECT * FROM read_json('{ndjson}', "
                f"format = 'newline_delimited', columns = {cols})")
    for name, f in (("ref_routes", "routes_ref.csv"), ("ref_route_category_history", "route_category_history.csv"),
                    ("ref_holidays", "holidays_ref.csv")):
        path = os.path.join(ref_dir, f)
        if not os.path.exists(path):
            raise FileNotFoundError(f"falta el archivo de referencia {path} (scripts/p3/generate_ref.sh)")
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_csv('{path}', header = true, all_varchar = true)")
    for stmt in (Q.EVENTS, Q.DIM_DATE, Q.DIM_FARE_CLASS, Q.DIM_ROUTE, Q.FACT_SEARCH, Q.FACT_BOOKING):
        con.execute(stmt)


def write_parquet(con, out_dir: str) -> dict:
    counts = {}
    for table, part in Q.TABLES:
        target = os.path.join(out_dir, table)
        os.makedirs(target, exist_ok=True)
        if part:
            con.execute(f"COPY (SELECT * FROM {table} ORDER BY {part}, date_key) TO '{target}' "
                        f"(FORMAT PARQUET, COMPRESSION SNAPPY, PARTITION_BY ({part}), OVERWRITE_OR_IGNORE)")
        else:
            con.execute(f"COPY (SELECT * FROM {table}) TO '{os.path.join(target, 'data.parquet')}' "
                        f"(FORMAT PARQUET, COMPRESSION SNAPPY)")
        counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return counts


def hive_columns(con, table: str, exclude: str | None) -> list[tuple[str, str]]:
    cols = []
    for name, typ, *_ in con.execute(f"DESCRIBE {table}").fetchall():
        if name == exclude:
            continue
        cols.append((name, _HIVE_TYPES[typ.upper()]))
    return cols


# --------------------------------------------------------------------------- Athena (DDL)
class Athena:
    def __init__(self, region, workgroup, output=None):
        import boto3
        self.c = boto3.client("athena", region_name=region)
        self.workgroup, self.output = workgroup, output

    def run(self, sql: str, database: str | None = None, timeout: int = 120):
        kw = {"QueryString": sql, "WorkGroup": self.workgroup}
        if database:
            kw["QueryExecutionContext"] = {"Database": database}
        if self.output:
            kw["ResultConfiguration"] = {"OutputLocation": self.output}
        qid = self.c.start_query_execution(**kw)["QueryExecutionId"]
        t0, wait = time.time(), 0.2
        while True:
            st = self.c.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
            if st["State"] == "SUCCEEDED":
                return qid
            if st["State"] in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"Athena {st['State']}: {st.get('StateChangeReason', '')}\n{sql[:300]}")
            if time.time() - t0 > timeout:
                raise TimeoutError(f"Athena no terminó en {timeout}s: {sql[:120]}")
            time.sleep(wait)
            wait = min(wait * 1.5, 1.0)


def _ddl(db, table, cols, part, location):
    body = ",\n  ".join(f"`{n}` {t}" for n, t in cols)
    parts = f"\nPARTITIONED BY (`{part}` string)" if part else ""
    return (f"CREATE EXTERNAL TABLE `{db}`.`{table}` (\n  {body}\n){parts}\nSTORED AS PARQUET\n"
            f"LOCATION '{location}'\nTBLPROPERTIES ('classification' = 'parquet')")


def _cleanup_old_builds(star: Lake, table: str, current: str):
    keys = star.list(f"{table}/")
    builds = sorted({k.split("/")[1] for k in keys if k.count("/") >= 2 and k.split("/")[1].startswith("build=")})
    keep = set(builds[-KEEP_BUILDS:]) | {f"build={current}"}
    star.delete([k for k in keys if k.split("/")[1] not in keep])


def publish(con, out_dir: str, build_id: str, star: Lake, settings) -> None:
    for table, part in Q.TABLES:
        base = os.path.join(out_dir, table)
        for dp, _, files in os.walk(base):
            for f in files:
                rel = os.path.relpath(os.path.join(dp, f), base).replace(os.sep, "/")
                star.upload_file(os.path.join(dp, f), f"{table}/build={build_id}/{rel}")

    if star.is_s3:
        ath = Athena(settings.AWS_REGION, settings.STAR_WORKGROUP, settings.ATHENA_OUTPUT or None)
        db = settings.STAR_DATABASE
        ath.run(f"CREATE DATABASE IF NOT EXISTS `{db}`")
        for table, part in Q.TABLES:
            loc = star.uri_for(f"{table}/build={build_id}/")
            ath.run(f"DROP TABLE IF EXISTS `{db}`.`{table}`")
            ath.run(_ddl(db, table, hive_columns(con, table, part), part, loc))
            if part:
                values = [r[0] for r in con.execute(f"SELECT DISTINCT {part} FROM {table} ORDER BY 1").fetchall()]
                for i in range(0, len(values), 50):
                    clauses = " ".join(f"PARTITION (`{part}` = '{v}') LOCATION '{loc}{part}={v}/'"
                                       for v in values[i:i + 50])
                    ath.run(f"ALTER TABLE `{db}`.`{table}` ADD IF NOT EXISTS {clauses}")
    else:
        # Modo local: un puntero a la corrida vigente (lo usa scripts/p3/local_check.py).
        star.put("_current.json", json.dumps({"build": build_id}).encode())

    for table, _ in Q.TABLES:
        _cleanup_old_builds(star, table, build_id)


# --------------------------------------------------------------------------- punto de entrada
def run_refresh(settings, flush_landing=None) -> dict:
    t0 = time.time()
    if flush_landing:
        flush_landing()     # lo que el consumidor tenga en memoria entra en esta corrida
    raw = Lake(settings.RAW_EVENTS_URI or os.path.join(settings.LOCAL_LAKE, "raw", "events"), settings.AWS_REGION)
    star = Lake(settings.STAR_URI or os.path.join(settings.LOCAL_LAKE, "star"), settings.AWS_REGION)
    build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    work = tempfile.mkdtemp(prefix="star-")
    try:
        paths = sync_raw(raw, os.path.join(settings.STATE_DIR, "raw-cache"))
        nd = os.path.join(work, "events.ndjson")
        stats = write_ndjson(paths, nd)
        con = duckdb.connect(":memory:")
        con.execute("SET threads TO 2")
        con.execute("SET memory_limit = '600MB'")
        build(con, nd, settings.REF_DIR)
        stats["distinct_events"] = con.execute("SELECT count(*) FROM events").fetchone()[0]
        stats["rows"] = write_parquet(con, os.path.join(work, "out"))
        publish(con, os.path.join(work, "out"), build_id, star, settings)
        con.close()
        stats.update({"build_id": build_id, "seconds": round(time.time() - t0, 1)})
        log.info("estrella reconstruida: %s", stats)
        return stats
    finally:
        shutil.rmtree(work, ignore_errors=True)
