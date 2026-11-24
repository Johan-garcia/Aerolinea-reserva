"""
Adaptador AWS local para correr el harness del Parcial 3 sin cuenta de AWS.

  * Kinesis  -> moto (boto3 real apuntando a AWS_ENDPOINT_URL): el backend y el worker usan el mismo.
  * S3       -> la landing zone local que escribe el worker (LOCAL_LAKE/raw/events).
  * Glue     -> esquema de los Parquet de la corrida vigente (LOCAL_LAKE/star/<tabla>/build=<id>/).
  * Athena   -> DuckDB con una vista por tabla; los bytes escaneados se aproximan con el tamaño de los
                archivos que la consulta realmente lee (poda por mes en fact_search).

Implementa la misma interfaz que parcial3-harness-estudiantes/harness/aws.py (RealAWS).
"""
import datetime as dt
import glob
import gzip
import json
import os
import re

import duckdb

UTC = dt.timezone.utc
_TYPE = {"INTEGER": "int", "BIGINT": "bigint", "BOOLEAN": "boolean", "DATE": "date", "VARCHAR": "string",
         "DOUBLE": "double"}


class LocalAWS:
    def __init__(self, lake: str, region: str, workgroup_cutoff: int):
        import boto3
        self.lake = lake
        self.raw = os.path.join(lake, "raw", "events")
        self.star = os.path.join(lake, "star")
        self.k = boto3.client("kinesis", region_name=region)
        self.cutoff = workgroup_cutoff

    # ------------------------------------------------------------------ estrella local
    def _build(self):
        with open(os.path.join(self.star, "_current.json"), encoding="utf-8") as fh:
            return json.load(fh)["build"]

    def _dir(self, table):
        return os.path.join(self.star, table, f"build={self._build()}")

    def _files(self, table, month=None):
        d = self._dir(table)
        if table == "fact_search":
            return sorted(glob.glob(os.path.join(d, f"month={month or '*'}", "*.parquet")))
        return sorted(glob.glob(os.path.join(d, "*.parquet")))

    def _con(self):
        con = duckdb.connect(":memory:")
        for t in ("dim_date", "dim_route", "dim_fare_class", "fact_booking_event"):
            con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet({self._files(t)!r})")
        con.execute(f"CREATE VIEW fact_search AS SELECT * FROM read_parquet({self._files('fact_search')!r}, "
                    f"hive_partitioning = true)")
        return con

    def athena_run(self, sql, database, workgroup, timeout=180):
        con = self._con()
        rows = con.execute(sql).fetchall()
        m = re.search(r"month\s*=\s*'(\d{4}-\d{2})'", sql)
        tables = [t for t in ("dim_date", "dim_route", "dim_fare_class", "fact_booking_event", "fact_search")
                  if re.search(rf"\b{t}\b", sql)]
        scanned = 0
        for t in tables:
            files = self._files(t, m.group(1) if (m and t == "fact_search") else None)
            scanned += sum(os.path.getsize(f) for f in files)
        out = [[None if v is None else (str(v).lower() if isinstance(v, bool) else str(v)) for v in r] for r in rows]
        return {"execution_id": "local", "rows": out, "data_scanned_bytes": scanned}

    def athena_list_executions(self, workgroup, limit=50):
        return []

    def athena_workgroup(self, workgroup):
        return {"bytes_cutoff": self.cutoff}

    def glue_get_table(self, database, name):
        try:
            files = self._files(name)
        except FileNotFoundError:
            return None
        if not files:
            return None
        con = duckdb.connect(":memory:")
        cols = [{"name": c, "type": _TYPE.get(t.upper(), t.lower())}
                for c, t, *_ in con.execute(f"DESCRIBE SELECT * FROM read_parquet({files[:1]!r})").fetchall()]
        parts = [{"name": "month", "type": "string"}] if name == "fact_search" else []
        return {"name": name, "columns": cols, "partition_keys": parts,
                "input_format": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "serde": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                "location": self._dir(name), "classification": "parquet", "projection_enabled": False}

    def glue_partition_count(self, database, name):
        return len(glob.glob(os.path.join(self._dir(name), "month=*")))

    # ------------------------------------------------------------------ S3 (landing local)
    def s3_list(self, uri):
        out = []
        for p in glob.glob(os.path.join(self.raw, "*")):
            out.append({"key": os.path.basename(p), "size": os.path.getsize(p),
                        "last_modified": dt.datetime.fromtimestamp(os.path.getmtime(p), UTC)})
        return out

    def s3_read_text_since(self, uri, since):
        out = []
        for o in self.s3_list(uri):
            if o["last_modified"] < since:
                continue
            with open(os.path.join(self.raw, o["key"]), "rb") as fh:
                body = fh.read()
            if body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            out.append((o["key"], body.decode("utf-8", errors="replace")))
        return out

    # ------------------------------------------------------------------ Kinesis (moto)
    def kinesis_summary(self, stream):
        try:
            s = self.k.describe_stream_summary(StreamName=stream)["StreamDescriptionSummary"]
        except self.k.exceptions.ResourceNotFoundException:
            return None
        try:
            n = len(self.k.list_stream_consumers(StreamARN=s["StreamARN"])["Consumers"])
        except Exception:  # noqa: BLE001
            n = 0
        return {"mode": s.get("StreamModeDetails", {}).get("StreamMode", "PROVISIONED"),
                "open_shards": int(s["OpenShardCount"]), "retention_hours": int(s["RetentionPeriodHours"]),
                "consumers": n}

    def kinesis_put(self, stream, records):
        from harness.aws import RealAWS
        return RealAWS.kinesis_put(self._as_real(), stream, records)

    def kinesis_read_since(self, stream, since, max_seconds=120):
        from harness.aws import RealAWS
        return RealAWS.kinesis_read_since(self._as_real(), stream, since, max_seconds)

    def _as_real(self):
        k = self.k

        class _R:
            def _c(self, name):
                return k
        return _R()

    # ------------------------------------------------------------------ el resto no aplica en local
    def account_id(self):
        return "000000000000"

    def compute_runs(self, days=45):
        return []

    def emr_usage(self, days=45):
        return None

    def rds_instances(self):
        return []

    def ec2_instances(self):
        return []

    def nat_gateways(self):
        return []

    def load_balancers(self):
        return []

    def other_billable(self):
        return {"counts": {}, "unknown": []}
