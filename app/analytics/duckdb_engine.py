"""
Motor DuckDB (desarrollo local): sustituto de Athena que lee el MISMO Parquet particionado
que escribe el job PySpark en LAKE_PATH/curated/. Las tablas se exponen como vistas con los
mismos nombres del Glue Data Catalog, de modo que la SQL es idéntica a la de Athena.

Cada consulta se anota en LAKE_PATH/_athena_local/query_log.jsonl (equivalente local al
historial de consultas de Athena), que usa el runner local del harness para verificar R7.
"""
import glob
import json
import os
import threading
import uuid
from datetime import datetime, timezone

import duckdb

from .base import AnalyticsUnavailable, QueryEngine


class DuckDBEngine(QueryEngine):
    name = "duckdb-local"

    def __init__(self, settings):
        super().__init__(settings)
        self.lake = settings.LAKE_PATH
        self.detail_glob = os.path.join(self.lake, "curated", self.detail, "month=*", "*.parquet")
        self.metrics_glob = os.path.join(self.lake, "curated", self.metrics, "*.parquet")
        self.log_path = os.path.join(self.lake, "_athena_local", "query_log.jsonl")
        self._local = threading.local()
        self._log_lock = threading.Lock()

    def _conn(self):
        # Una conexión por hilo: DuckDB no comparte cursores entre hilos.
        con = getattr(self._local, "con", None)
        if con is None:
            con = duckdb.connect(database=":memory:")
            con.execute("SET threads TO 2")
            self._local.con = con
        if not glob.glob(self.metrics_glob):
            raise AnalyticsUnavailable(
                "No hay datos curados todavía: ejecute el job PySpark (docker compose --profile batch run --rm spark-job)."
            )
        # Se recrean las vistas en cada consulta para ver siempre la última corrida del job.
        con.execute(f"CREATE OR REPLACE VIEW {self.metrics} AS SELECT * FROM read_parquet('{self.metrics_glob}')")
        if glob.glob(self.detail_glob):
            con.execute(
                f"CREATE OR REPLACE VIEW {self.detail} AS SELECT * FROM "
                f"read_parquet('{self.detail_glob}', hive_partitioning = true)"
            )
        return con

    def query(self, sql: str, params: list[str]) -> list[dict]:
        submitted = datetime.now(timezone.utc)
        cur = self._conn().execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        self._log(sql, params, submitted)
        return rows

    def _log(self, sql, params, submitted):
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            rec = {"id": uuid.uuid4().hex, "state": "SUCCEEDED", "query": sql, "params": params,
                   "submitted_at": submitted.isoformat(), "engine": self.name}
            with self._log_lock, open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        except OSError:
            pass
