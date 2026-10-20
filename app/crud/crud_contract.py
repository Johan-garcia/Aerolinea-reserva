"""
Lógica transaccional del contrato del Parcial 2.

Control de concurrencia (R2): en lugar de SELECT ... FOR UPDATE seguido de un UPDATE,
se usa un único UPDATE condicional

    UPDATE flights SET seats_available = seats_available - 1
    WHERE flight_id = :id AND seats_available > 0
    RETURNING price_cents

PostgreSQL toma el bloqueo de fila al ejecutar el UPDATE; las transacciones concurrentes
esperan y, en READ COMMITTED, re-evalúan la condición seats_available > 0 sobre la versión
ya confirmada. Con K asientos exactamente K transacciones obtienen fila; el resto recibe
0 filas y se responde 409. El bloqueo dura solo lo que tarda el INSERT de la reserva.
"""
import secrets
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.contract import Flight, Reservation
from app.schemas.contract import FlightCreate, ReservationCreate

# Ejecutiva paga 2,5 veces la tarifa económica, igual que en el histórico generado.
MULTIPLICADOR_EJECUTIVA = 2.5


def precio_ejecutiva(precio_economica: int) -> int:
    return int(round(precio_economica * MULTIPLICADOR_EJECUTIVA))


# Alfabeto sin caracteres ambiguos (0/O, 1/I) para que el id sea fácil de dictar.
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class FlightNotFound(Exception):
    pass


class SoldOut(Exception):
    pass


def nuevo_reservation_id() -> str:
    return "R" + "".join(secrets.choice(_ALFABETO) for _ in range(11))


def crear_vuelo(db: Session, data: FlightCreate) -> Flight | None:
    """Inserta el vuelo; devuelve None si el flight_id ya existe (-> 409)."""
    origin, destination = data.route.split("-")
    stmt = (
        pg_insert(Flight)
        .values(
            flight_id=data.flight_id,
            route=data.route,
            origin=origin,
            destination=destination,
            flight_date=data.flight_date,
            capacity=data.capacity,
            seats_available=data.capacity,
            price_cents=data.price_cents,
        )
        .on_conflict_do_nothing(index_elements=["flight_id"])
        .returning(Flight.flight_id)
    )
    creado = db.execute(stmt).scalar_one_or_none()
    db.commit()
    if creado is None:
        return None
    return db.get(Flight, creado)


def buscar_vuelos(db: Session, origin: str, destination: str, fecha: date) -> list[Flight]:
    stmt = (
        select(Flight)
        .where(
            Flight.origin == origin.upper(),
            Flight.destination == destination.upper(),
            Flight.flight_date == fecha,
            Flight.seats_available > 0,
        )
        .order_by(Flight.price_cents, Flight.flight_id)
    )
    return list(db.execute(stmt).scalars())


def rutas_disponibles(db: Session, desde: date) -> list[dict]:
    """Rutas con al menos un vuelo futuro con sillas, y la primera fecha en que hay vuelo."""
    stmt = (
        select(Flight.route, Flight.origin, Flight.destination, func.min(Flight.flight_date).label("next_date"))
        .where(Flight.flight_date >= desde, Flight.seats_available > 0)
        .group_by(Flight.route, Flight.origin, Flight.destination)
        .order_by(Flight.origin, Flight.destination)
    )
    return [r._asdict() for r in db.execute(stmt)]


def reservar(db: Session, data: ReservationCreate) -> Reservation:
    """Reserva un asiento de forma atómica. Lanza FlightNotFound (404) o SoldOut (409)."""
    precio = db.execute(
        text(
            "UPDATE flights SET seats_available = seats_available - 1 "
            "WHERE flight_id = :fid AND seats_available > 0 RETURNING price_cents"
        ),
        {"fid": data.flight_id},
    ).scalar_one_or_none()

    if precio is None:
        db.rollback()
        if db.get(Flight, data.flight_id) is None:
            raise FlightNotFound(data.flight_id)
        raise SoldOut(data.flight_id)

    if data.fare_class == "BUSINESS":
        precio = precio_ejecutiva(precio)

    reserva = Reservation(
        reservation_id=nuevo_reservation_id(),
        flight_id=data.flight_id,
        passenger_name=data.passenger_name.strip(),
        fare_class=data.fare_class,
        status="CONFIRMED",
        price_cents=precio,
    )
    db.add(reserva)
    db.commit()
    return reserva


def obtener_reserva(db: Session, reservation_id: str) -> Reservation | None:
    return db.get(Reservation, reservation_id)
