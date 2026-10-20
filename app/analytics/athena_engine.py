"""Motor Amazon Athena (despliegue AWS). Requiere credenciales del rol de la instancia / Learner Lab."""
import time

from .base import AnalyticsError, AnalyticsUnavailable, QueryEngine

_INT_TYPES = {"tinyint", "smallint", "integer", "bigint"}
_FLOAT_TYPES = {"double", "float", "real", "decimal"}


def _cast(value, typ):
    if value is None:
        return None
    if typ in _INT_TYPES:
        return int(value)
    if typ in _FLOAT_TYPES:
        return float(value)
    return value


class AthenaEngine(QueryEngine):
    name = "athena"

    def __init__(self, settings):
        super().__init__(settings)
        import boto3
        self.client = boto3.client("athena", region_name=settings.AWS_REGION)

    def query(self, sql: str, params: list[str]) -> list[dict]:
        kw = dict(
            QueryString=sql,
            QueryExecutionContext={"Database": self.s.ATHENA_DATABASE},
            WorkGroup=self.s.ATHENA_WORKGROUP,
        )
        if params:
            # Athena recibe literales SQL; los valores ya pasaron por una regex estricta.
            kw["ExecutionParameters"] = ["'" + p.replace("'", "''") + "'" for p in params]
        if self.s.ATHENA_OUTPUT:
            kw["ResultConfiguration"] = {"OutputLocation": self.s.ATHENA_OUTPUT}
        try:
            qid = self.client.start_query_execution(**kw)["QueryExecutionId"]
        except Exception as e:  # noqa: BLE001
            raise AnalyticsUnavailable(f"Athena no disponible: {e}") from e

        deadline = time.monotonic() + self.s.ANALYTICS_TIMEOUT_SECONDS
        wait = 0.1
        while True:
            st = self.client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
            if st["State"] == "SUCCEEDED":
                break
            if st["State"] in ("FAILED", "CANCELLED"):
                raise AnalyticsError(f"Athena {st['State']}: {st.get('StateChangeReason', '')}")
            if time.monotonic() > deadline:
                self.client.stop_query_execution(QueryExecutionId=qid)
                raise AnalyticsError("Athena excedió el tiempo límite")
            time.sleep(wait)
            wait = min(wait * 1.5, 0.5)

        out, cols, first = [], None, True
        for page in self.client.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
            if cols is None:
                cols = [(c["Name"], c["Type"].lower()) for c in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
            for row in page["ResultSet"]["Rows"]:
                if first:  # la primera fila de un SELECT es el encabezado
                    first = False
                    continue
                vals = [c.get("VarCharValue") for c in row["Data"]]
                out.append({n: _cast(v, t) for (n, t), v in zip(cols, vals)})
        return out
