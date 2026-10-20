"""
Esquemas Pydantic del contrato del Parcial 2 (parcial2-harness/contract/API.md).
Los nombres de campo están en inglés porque el harness los valida textualmente.
"""
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, field_validator

ROUTE_PATTERN = r"^[A-Z]{3}-[A-Z]{3}$"


class FlightCreate(BaseModel):
    flight_id: str = Field(..., min_length=1, max_length=64)
    route: str = Field(..., examples=["BOG-MDE"])
    flight_date: date
    capacity: int = Field(..., gt=0, le=1000)
    price_cents: int = Field(..., gt=0)

    @field_validator("route")
    @classmethod
    def normalizar_ruta(cls, v: str) -> str:
        # Misma regla C1 del pipeline: sin espacios y en mayúsculas.
        v = "".join(v.split()).upper()
        if len(v) != 7 or v[3] != "-" or not (v[:3] + v[4:]).isalpha():
            raise ValueError("route debe tener la forma AAA-BBB")
        return v


class FlightOut(BaseModel):
    flight_id: str
    route: str
    flight_date: date
    seats_available: int
    price_cents: int
    price_business_cents: int | None = None   # extra, no lo exige el contrato


class ReservationCreate(BaseModel):
    flight_id: str = Field(..., min_length=1, max_length=64)
    passenger_name: str = Field(..., min_length=1, max_length=200)
    fare_class: Literal["ECONOMY", "BUSINESS"] = "ECONOMY"


class ReservationOut(BaseModel):
    reservation_id: str
    flight_id: str
    status: str
    passenger_name: str
    fare_class: str | None = None
    # Extras (el contrato no los exige): sirven para mostrar y consultar la reserva en el frontend.
    price_cents: int | None = None
    route: str | None = None
    flight_date: date | None = None


class OccupancyOut(BaseModel):
    route: str
    month: str
    occupancy: float
    seats_sold: int
    seats_capacity: int
    revenue_cents: int | None = None
    bookings: int | None = None
    cancellations: int | None = None
    source: str


class RouteOccupancyOut(BaseModel):
    route: str
    occupancy: float
    seats_sold: int
    seats_capacity: int
