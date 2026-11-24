"""Construcción de eventos según el contrato (Appendix A.1). Nunca llevan datos personales."""
import uuid
from datetime import date, datetime, timezone

SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    """event_ts = cuándo ocurrió, en UTC y con el formato exacto YYYY-MM-DDTHH:MM:SSZ."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(event_type: str) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "event_ts": utc_now_iso(),
        "schema_version": SCHEMA_VERSION,
    }


def search_event(session_id: str | None, origin: str, destination: str, travel_date: date,
                 results_count: int) -> tuple[str, dict]:
    """Devuelve (partition_key, evento). La clave de partición de una búsqueda es session_id."""
    e = _envelope("search_performed")
    e.update({
        "session_id": session_id or f"anon-{uuid.uuid4().hex}",
        "origin": origin.upper(),
        "destination": destination.upper(),
        "travel_date": travel_date.isoformat(),
        "results_count": int(results_count),
    })
    return e["session_id"], e


def reservation_event(event_type: str, *, reservation_id: str, flight_id: str, route: str,
                      flight_date: date, fare_class: str, price_cents: int) -> tuple[str, dict]:
    """reservation_created / reservation_cancelled. Clave de partición: flight_id.
    El nombre del pasajero NO se incluye (minimización de datos personales)."""
    assert event_type in ("reservation_created", "reservation_cancelled")
    e = _envelope(event_type)
    e.update({
        "reservation_id": reservation_id,
        "flight_id": flight_id,
        "route": route,
        "flight_date": flight_date.isoformat() if hasattr(flight_date, "isoformat") else str(flight_date),
        "fare_class": fare_class,
        "price_cents": int(price_cents),
    })
    return flight_id, e
