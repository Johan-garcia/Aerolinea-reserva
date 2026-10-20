"""
Adaptador "AWS local" para correr el harness del Parcial 2 sin cuenta de AWS.

Implementa la misma interfaz que parcial2-harness/harness/aws.py::RealAWS, pero sobre lo que
produce el sistema en local:

  S3 / Glue  -> data/lake/curated/  (Parquet escrito por el job PySpark)
  Athena     -> DuckDB sobre ese Parquet; el historial sale de data/lake/_athena_local/query_log.jsonl,
                que escribe el backend cada vez que consulta (así R7 verifica que el endpoint consultó)
  EMR        -> data/lake/_emr_local/runs.jsonl, que escribe el job Spark al terminar
  RDS/EC2/…  -> se simula el despliegue PLANEADO de local_harness/simulated_deployment.yaml

Lo que es aproximado (y no reemplaza la corrida real en AWS):
  * data_scanned_bytes: se estima como el tamaño de las particiones que la consulta toca
    (DuckDB, como Athena, solo abre month=X cuando la consulta filtra por month).
  * R10-R12 verifican el despliegue planeado, no recursos reales.
"""
import datetime as dt
import glob
import json
import os
import re
import time

import duckdb
import yaml

HIVE_TYPES = {"VARCHAR": "string", "BIGINT": "bigint", "DOUBLE": "double", "INTEGER": "int"}


def _utc(ts: str):
    d = dt.datetime.fromisoformat(ts)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


class LocalAWS:
    def __init__(self, lake: str, tables: dict, deployment_file: str):
        self.lake = os.path.abspath(lake)
        self.curated = os.path.join(self.lake, "curated")
        self.detail, self.metrics = tables["detail"], tables["metrics"]
        with open(deployment_file, encoding="utf-8") as fh:
            self.deploy = yaml.safe_load(fh) or {}

    # ------------------------------------------------------------------ helpers
    def _loc(self, table):
        return os.path.join(self.curated, table)

    def _con(self):
        con = duckdb.connect()
        con.execute(f"CREATE VIEW {self.metrics} AS SELECT * FROM read_parquet('{self._loc(self.metrics)}/*.parquet')")
        con.execute(f"CREATE VIEW {self.detail} AS SELECT * FROM "
                    f"read_parquet('{self._loc(self.detail)}/month=*/*.parquet', hive_partitioning = true)")
        return con

    def _files(self, table, month=None):
        pat = os.path.join(self._loc(table), f"month={month}" if month else "**", "*.parquet")
        return glob.glob(pat, recursive=True)

    # ------------------------------------------------------------------- identity
    def account_id(self):
        return "local"

    # --------------------------------------------------------------------- Athena
    def athena_run(self, sql, database, workgroup, timeout=180):
        con = self._con()
        cur = con.execute(sql)
        rows = [[None if v is None else str(v) for v in r] for r in cur.fetchall()]
        table = self.detail if re.search(rf"\b{self.detail}\b", sql) else self.metrics
        m = re.search(r"month\s*=\s*'(\d{4}-\d{2})'", sql) if table == self.detail else None
        scanned = sum(os.path.getsize(f) for f in self._files(table, m.group(1) if m else None))
        return {"execution_id": f"local-{time.time_ns()}", "rows": rows, "data_scanned_bytes": scanned}

    def athena_list_executions(self, workgroup, limit=50):
        path = os.path.join(self.lake, "_athena_local", "query_log.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            recs = [json.loads(line) for line in fh if line.strip()][-limit:]
        return [{"id": r["id"], "state": r["state"], "query": r["query"], "data_scanned_bytes": 0,
                 "submitted_at": _utc(r["submitted_at"])} for r in reversed(recs)]

    # ----------------------------------------------------------------------- Glue
    def glue_get_table(self, database, name):
        if not self._files(name):
            return None
        con = duckdb.connect()
        if name == self.detail:
            src = f"read_parquet('{self._loc(name)}/month=*/*.parquet', hive_partitioning = false)"
        else:
            src = f"read_parquet('{self._loc(name)}/*.parquet')"
        cols = [{"name": r[0], "type": HIVE_TYPES.get(r[1], r[1].lower())}
                for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
        parts = [{"name": "month", "type": "string"}] if name == self.detail else []
        return {"name": name, "columns": cols, "partition_keys": parts,
                "input_format": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "serde": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                "location": self._loc(name), "classification": "parquet", "projection_enabled": False}

    def glue_partition_count(self, database, name):
        return len(glob.glob(os.path.join(self._loc(name), "month=*")))

    # ------------------------------------------------------------------------- S3
    def s3_list(self, uri):
        out = []
        for root, _, files in os.walk(uri):
            for f in files:
                p = os.path.join(root, f)
                st = os.stat(p)
                out.append({"key": os.path.relpath(p, self.lake), "size": st.st_size,
                            "last_modified": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc)})
        return out

    # ------------------------------------------------------------------------ EMR
    def compute_runs(self, days=45):
        path = os.path.join(self.lake, "_emr_local", "runs.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [{"kind": "emr-local", "id": r["id"], "cluster_id": "local-spark", "state": r["state"],
                     "started_at": _utc(r["started_at"]), "ended_at": _utc(r["ended_at"])}
                    for r in map(json.loads, filter(str.strip, fh))]

    def emr_usage(self, days=45):
        e = self.deploy.get("emr", {})
        return {"active_clusters": [], "started_serverless_apps": 0,
                "normalized_instance_hours": float(e.get("normalized_instance_hours", 0)),
                "instance_types": e.get("instance_types", [])}

    # ------------------------------------------------- recursos facturables (simulados)
    def rds_instances(self):
        return self.deploy.get("rds", [])

    def ec2_instances(self):
        return self.deploy.get("ec2", [])

    def nat_gateways(self):
        return []

    def load_balancers(self):
        return []

    def other_billable(self):
        return {"counts": {}, "unknown": []}
