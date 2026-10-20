"""
Prueba del motor Athena sin AWS: un cliente falso imita las respuestas de boto3 para verificar
qué se envía a Athena (base de datos, workgroup, parámetros) y cómo se convierten los resultados.
"""
from types import SimpleNamespace

import pytest

from app.analytics.athena_engine import AthenaEngine
from app.analytics.base import AnalyticsError


class FakeAthena:
    def __init__(self, states, rows):
        self.states = list(states)
        self.rows = rows
        self.started = []

    def start_query_execution(self, **kw):
        self.started.append(kw)
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, QueryExecutionId):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"QueryExecution": {"Status": {"State": state, "StateChangeReason": "boom"}}}

    def stop_query_execution(self, QueryExecutionId):
        pass

    def get_paginator(self, name):
        cols = [{"Name": "route", "Type": "varchar"}, {"Name": "month", "Type": "varchar"},
                {"Name": "seats_capacity", "Type": "bigint"}, {"Name": "seats_sold", "Type": "bigint"},
                {"Name": "occupancy", "Type": "double"}]
        header = {"Data": [{"VarCharValue": c["Name"]} for c in cols]}
        data = [{"Data": [{"VarCharValue": v} for v in r]} for r in self.rows]
        page = {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": cols}, "Rows": [header] + data}}
        return SimpleNamespace(paginate=lambda **kw: [page])


def make_engine(fake, **over):
    s = SimpleNamespace(METRICS_TABLE="route_month_metrics", DETAIL_TABLE="reservations_curated",
                        ATHENA_DATABASE="airline_analytics", ATHENA_WORKGROUP="primary",
                        ATHENA_OUTPUT="s3://b/athena-results/", AWS_REGION="us-east-1",
                        ANALYTICS_TIMEOUT_SECONDS=2.0)
    for k, v in over.items():
        setattr(s, k, v)
    eng = AthenaEngine.__new__(AthenaEngine)
    eng.s, eng.metrics, eng.detail, eng.client = s, s.METRICS_TABLE, s.DETAIL_TABLE, fake
    return eng


def test_occupancy_envia_parametros_y_convierte_tipos():
    fake = FakeAthena(["QUEUED", "RUNNING", "SUCCEEDED"], [["BGA-BOG", "2024-03", "9360", "7069", "0.7552350427350427"]])
    row = make_engine(fake).occupancy("BGA-BOG", "2024-03")
    kw = fake.started[0]
    assert kw["QueryExecutionContext"] == {"Database": "airline_analytics"}
    assert kw["WorkGroup"] == "primary"
    assert kw["ExecutionParameters"] == ["'BGA-BOG'", "'2024-03'"]
    assert kw["ResultConfiguration"] == {"OutputLocation": "s3://b/athena-results/"}
    assert "FROM route_month_metrics WHERE route = ? AND month = ?" in kw["QueryString"]
    assert row == {"route": "BGA-BOG", "month": "2024-03", "seats_capacity": 9360,
                   "seats_sold": 7069, "occupancy": 0.7552350427350427}


def test_sin_filas_devuelve_none():
    assert make_engine(FakeAthena(["SUCCEEDED"], [])).occupancy("ZZZ-YYY", "2023-01") is None


def test_consulta_fallida_lanza_error():
    with pytest.raises(AnalyticsError):
        make_engine(FakeAthena(["FAILED"], [])).occupancy("BGA-BOG", "2024-03")


def test_timeout_lanza_error():
    with pytest.raises(AnalyticsError):
        make_engine(FakeAthena(["RUNNING"], []), ANALYTICS_TIMEOUT_SECONDS=0.3).occupancy("BGA-BOG", "2024-03")
