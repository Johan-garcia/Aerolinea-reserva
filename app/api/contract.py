"""
Endpoints del contrato del Parcial 2 (Appendix A.1), montados en la raíz del servicio
porque el harness los llama sin prefijo. La API del Parcial 1 sigue disponible en /api/v1.
"""
from datetime import date
from datetime import date as date_cls
from typing import List

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics import MONTH_RE, ROUTE_RE, AnalyticsError, AnalyticsUnavailable, cache, get_engine
from app.core.config import settings
from app.core.database import get_db
from app.events import publisher, reservation_event, search_event
from app.crud import crud_contract as crud
from app.models.contract import Flight
from app.schemas.contract import (
    CancellationRouteOut,
    FlightCreate,
    LiveOut,
    FlightOut,
    OccupancyOut,
    ReservationCreate,
    ReservationOut,
    RouteOccupancyOut,
)

router = APIRouter()


def _reserva_out(r, db: Session) -> ReservationOut:
    vuelo = db.get(Flight, r.flight_id)
    return ReservationOut(
        reservation_id=r.reservation_id,
        flight_id=r.flight_id,
        status=r.status,
        passenger_name=r.passenger_name,
        fare_class=r.fare_class,
        price_cents=r.price_cents,
        route=vuelo.route if vuelo else None,
        flight_date=vuelo.flight_date if vuelo else None,
    )


# ----------------------------------------------------------------------------- salud
@router.get("/health", tags=["Contrato P2"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "analytics_engine": get_engine().name}


# --------------------------------------------------------------------------- vuelos
@router.post("/admin/flights", status_code=status.HTTP_201_CREATED, response_model=FlightCreate, tags=["Contrato P2"])
def crear_vuelo(data: FlightCreate, db: Session = Depends(get_db)):
    if crud.crear_vuelo(db, data) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"El vuelo {data.flight_id} ya existe")
    return data


@router.get("/flights/search", response_model=List[FlightOut], tags=["Contrato P2"])
def buscar_vuelos(
    origin: str = Query(..., pattern=r"^[A-Za-z]{3}$"),
    destination: str = Query(..., pattern=r"^[A-Za-z]{3}$"),
    date: date = Query(...),
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
    db: Session = Depends(get_db),
):
    vuelos = [
        FlightOut(
            flight_id=f.flight_id,
            route=f.route,
            flight_date=f.flight_date,
            seats_available=f.seats_available,
            price_cents=f.price_cents,
            price_business_cents=crud.precio_ejecutiva(f.price_cents),
        )
        for f in crud.buscar_vuelos(db, origin, destination, date)
    ]
    # Parcial 3 (R1/R2): un search_performed por llamada, encolado sin esperar a Kinesis.
    publisher.publish(*search_event(x_session_id, origin, destination, date, len(vuelos)))
    return vuelos


@router.get("/flights/routes", tags=["Contrato P2"])
def rutas_con_vuelos(db: Session = Depends(get_db)):
    """Rutas que el cliente puede elegir: con vuelos desde hoy y sillas disponibles."""
    return crud.rutas_disponibles(db, date_cls.today())


# -------------------------------------------------------------------------- reservas
@router.post("/reservations", status_code=status.HTTP_201_CREATED, response_model=ReservationOut, tags=["Contrato P2"])
def crear_reserva(data: ReservationCreate, db: Session = Depends(get_db)):
    try:
        out = _reserva_out(crud.reservar(db, data), db)
    except crud.FlightNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"El vuelo {data.flight_id} no existe")
    except crud.SoldOut:
        raise HTTPException(status.HTTP_409_CONFLICT, "No quedan asientos en este vuelo")
    # Se publica DESPUÉS del commit: nunca se anuncia una reserva que no quedó guardada.
    _publicar_reserva("reservation_created", out)
    return out


def _publicar_reserva(event_type: str, r: ReservationOut) -> None:
    publisher.publish(*reservation_event(
        event_type, reservation_id=r.reservation_id, flight_id=r.flight_id, route=r.route,
        flight_date=r.flight_date, fare_class=r.fare_class, price_cents=r.price_cents), critical=True)


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationOut, tags=["Contrato P3"])
def cancelar_reserva(reservation_id: str, db: Session = Depends(get_db)):
    """Cancela la reserva, libera la silla y publica reservation_cancelled (404 si no existe, 409 si ya estaba cancelada)."""
    try:
        out = _reserva_out(crud.cancelar(db, reservation_id), db)
    except crud.ReservationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"La reserva {reservation_id} no existe")
    except crud.AlreadyCancelled:
        raise HTTPException(status.HTTP_409_CONFLICT, f"La reserva {reservation_id} ya estaba cancelada")
    _publicar_reserva("reservation_cancelled", out)
    return out


@router.get("/reservations/{reservation_id}", response_model=ReservationOut, tags=["Contrato P2"])
def obtener_reserva(reservation_id: str, db: Session = Depends(get_db)):
    r = crud.obtener_reserva(db, reservation_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"La reserva {reservation_id} no existe")
    return _reserva_out(r, db)


# ------------------------------------------------------------------------- analítica
def _consultar(fn, *args):
    try:
        return fn(*args)
    except AnalyticsUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except AnalyticsError as e:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(e))


@router.get("/analytics/occupancy", response_model=OccupancyOut, tags=["Analítica"])
def ocupacion(
    response: Response,
    route: str = Query(..., examples=["BOG-MDE"]),
    month: str = Query(..., examples=["2024-03"]),
):
    route = "".join(route.split()).upper()
    if not ROUTE_RE.match(route) or not MONTH_RE.match(month):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use route=AAA-BBB y month=YYYY-MM")

    engine = get_engine()
    key = ("occ", route, month)
    row = cache.get(key)
    response.headers["X-Analytics-Cache"] = "HIT" if row else "MISS"
    if row is None:
        row = _consultar(engine.occupancy, route, month)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sin datos para {route} en {month}")
        cache.put(key, row)
    return OccupancyOut(**row, source=engine.name)


@router.get("/analytics/top-routes", response_model=List[RouteOccupancyOut], tags=["Analítica"])
def top_rutas(limit: int = Query(10, ge=1, le=50)):
    key = ("top", limit)
    rows = cache.get(key)
    if rows is None:
        rows = _consultar(get_engine().top_routes, limit)
        cache.put(key, rows)
    return rows


@router.get("/analytics/catalog", tags=["Analítica"])
def catalogo():
    """Rutas y meses disponibles, para autocompletar el panel gerencial."""
    data = cache.get(("catalog",))
    if data is None:
        data = _consultar(get_engine().catalog)
        cache.put(("catalog",), data)
    return data


@router.get("/analytics/cancellations", response_model=List[CancellationRouteOut], tags=["Analítica"])
def cancelaciones_por_ruta(month: str | None = Query(None, examples=["2024-03"])):
    """Reservas confirmadas, cancelaciones y tasa de cancelación por ruta (histórico del Parcial 2).
    Sin `month` acumula los 24 meses; con `month` (YYYY-MM) filtra ese mes."""
    if month is not None and not MONTH_RE.match(month):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use month=YYYY-MM")
    key = ("cancel", month)
    rows = cache.get(key)
    if rows is None:
        rows = _consultar(get_engine().cancellations_by_route, month)
        cache.put(key, rows)
    return rows


# --------------------------------------------------------------- Parcial 3: worker
# La vista en vivo y el job de la estrella viven en el proceso worker (un único consumidor del
# stream). La API solo reenvía: así los 2 workers de uvicorn ven los mismos contadores.
_worker = httpx.Client(base_url=settings.WORKER_URL, timeout=httpx.Timeout(5.0, connect=2.0))


def _al_worker(method: str, path: str, **kw):
    try:
        r = _worker.request(method, path, **kw)
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"El worker de eventos no responde: {e}")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text or "error del worker"
        raise HTTPException(r.status_code, detail)
    return r


@router.get("/analytics/live", response_model=LiveOut, tags=["Contrato P3"])
def vista_en_vivo(window: int = Query(5, ge=1, le=60)):
    """Búsquedas, reservas y cancelaciones cuyo event_ts cae en los últimos `window` minutos.
    La alimenta el consumidor del stream de Kinesis (no Athena)."""
    return _al_worker("GET", "/live", params={"window": window}).json()


@router.post("/admin/refresh-star", status_code=status.HTTP_202_ACCEPTED, tags=["Contrato P3"])
def refrescar_estrella():
    """Lanza (o encola, si ya hay uno corriendo) el job que reconstruye la estrella desde la landing zone."""
    return _al_worker("POST", "/refresh").json()


@router.get("/admin/refresh-status", tags=["Contrato P3"])
def estado_refresco():
    return _al_worker("GET", "/status").json()


@router.get("/admin/events-stats", tags=["Contrato P3"])
def estadisticas_eventos():
    """Diagnóstico del publicador de este proceso (enviados, descartados, en cola)."""
    return publisher.stats()
