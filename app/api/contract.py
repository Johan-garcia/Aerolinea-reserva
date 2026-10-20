"""
Endpoints del contrato del Parcial 2 (Appendix A.1), montados en la raíz del servicio
porque el harness los llama sin prefijo. La API del Parcial 1 sigue disponible en /api/v1.
"""
from datetime import date
from datetime import date as date_cls
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics import MONTH_RE, ROUTE_RE, AnalyticsError, AnalyticsUnavailable, cache, get_engine
from app.core.database import get_db
from app.crud import crud_contract as crud
from app.models.contract import Flight
from app.schemas.contract import (
    FlightCreate,
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
    db: Session = Depends(get_db),
):
    return [
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


@router.get("/flights/routes", tags=["Contrato P2"])
def rutas_con_vuelos(db: Session = Depends(get_db)):
    """Rutas que el cliente puede elegir: con vuelos desde hoy y sillas disponibles."""
    return crud.rutas_disponibles(db, date_cls.today())


# -------------------------------------------------------------------------- reservas
@router.post("/reservations", status_code=status.HTTP_201_CREATED, response_model=ReservationOut, tags=["Contrato P2"])
def crear_reserva(data: ReservationCreate, db: Session = Depends(get_db)):
    try:
        return _reserva_out(crud.reservar(db, data), db)
    except crud.FlightNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"El vuelo {data.flight_id} no existe")
    except crud.SoldOut:
        raise HTTPException(status.HTTP_409_CONFLICT, "No quedan asientos en este vuelo")


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
