from abc import ABC, abstractmethod


class AnalyticsError(Exception):
    """La consulta falló o excedió el tiempo límite."""


class AnalyticsUnavailable(AnalyticsError):
    """Aún no existen datos curados (el job PySpark no ha corrido)."""


class QueryEngine(ABC):
    name: str = "engine"

    def __init__(self, settings):
        self.s = settings
        self.metrics = settings.METRICS_TABLE
        self.detail = settings.DETAIL_TABLE

    @abstractmethod
    def query(self, sql: str, params: list[str]) -> list[dict]:
        """Ejecuta SQL con parámetros posicionales (?) que son siempre strings ya validados."""

    # Consultas de negocio: una sola fuente de verdad para ambos motores.
    def occupancy(self, route: str, month: str) -> dict | None:
        rows = self.query(
            f"SELECT route, month, seats_capacity, seats_sold, occupancy, revenue_cents, bookings, cancellations "
            f"FROM {self.metrics} WHERE route = ? AND month = ?",
            [route, month],
        )
        return rows[0] if rows else None

    def top_routes(self, limit: int) -> list[dict]:
        return self.query(
            f"SELECT route, CAST(sum(seats_sold) AS DOUBLE) / sum(seats_capacity) AS occupancy, "
            f"sum(seats_sold) AS seats_sold, sum(seats_capacity) AS seats_capacity "
            f"FROM {self.metrics} GROUP BY route ORDER BY occupancy DESC LIMIT {int(limit)}",
            [],
        )

    def catalog(self) -> dict:
        rows = self.query(f"SELECT DISTINCT route, month FROM {self.metrics}", [])
        return {
            "routes": sorted({r["route"] for r in rows}),
            "months": sorted({r["month"] for r in rows}),
        }
