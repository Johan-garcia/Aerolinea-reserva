"""
Capa analítica del Parcial 2.

El endpoint /analytics/occupancy nunca toca la base transaccional (separación de cargas,
R1/R2): consulta la tabla route_month_metrics que produce el job PySpark (EMR).

  * ANALYTICS_ENGINE=athena -> Amazon Athena sobre el Glue Data Catalog (despliegue AWS, R7).
  * ANALYTICS_ENGINE=duckdb -> DuckDB leyendo el mismo Parquet en disco (desarrollo local).

Ambos motores ejecutan la misma SQL, así que pasar a AWS es solo cambiar variables de entorno.
"""
import re
import threading
import time

from app.core.config import settings

from .base import AnalyticsError, AnalyticsUnavailable, QueryEngine

ROUTE_RE = re.compile(r"^[A-Z]{3}-[A-Z]{3}$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

_engine: QueryEngine | None = None
_lock = threading.Lock()


def get_engine() -> QueryEngine:
    global _engine
    with _lock:
        if _engine is None:
            if settings.ANALYTICS_ENGINE.lower() == "athena":
                from .athena_engine import AthenaEngine
                _engine = AthenaEngine(settings)
            else:
                from .duckdb_engine import DuckDBEngine
                _engine = DuckDBEngine(settings)
        return _engine


class TTLCache:
    """Caché mínima en memoria. La primera petición de cada (ruta, mes) siempre consulta
    el motor (el contrato lo exige); las repeticiones dentro del TTL no pagan otra consulta."""

    def __init__(self, ttl: int):
        self.ttl = ttl
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        if self.ttl <= 0:
            return None
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            self._data.pop(key, None)
            return None

    def put(self, key, value):
        if self.ttl <= 0:
            return
        with self._lock:
            if len(self._data) > 2048:
                self._data.clear()
            self._data[key] = (time.monotonic() + self.ttl, value)


cache = TTLCache(settings.ANALYTICS_CACHE_TTL_SECONDS)

__all__ = ["get_engine", "cache", "ROUTE_RE", "MONTH_RE", "AnalyticsError", "AnalyticsUnavailable"]
