"""
Modelos del contrato del Parcial 2 (Appendix A.1).

Son deliberadamente simples: el harness solo habla con el backend a través de
POST /admin/flights, GET /flights/search, POST /reservations y GET /reservations/{id}.
El inventario vive en la columna seats_available, que se decrementa con un UPDATE
condicional (ver app/crud/crud_contract.py) para garantizar 0 % de sobreventa (R2).
"""
from datetime import date, datetime
from sqlalchemy import String, Integer, BigInteger, Date, DateTime, ForeignKey, Index, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Flight(Base):
    __tablename__ = "flights"
    __table_args__ = (
        CheckConstraint("seats_available >= 0", name="ck_flights_seats_non_negative"),
        CheckConstraint("seats_available <= capacity", name="ck_flights_seats_le_capacity"),
        Index("ix_flights_search", "origin", "destination", "flight_date"),
    )

    flight_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    route: Mapped[str] = mapped_column(String(16), nullable=False)
    origin: Mapped[str] = mapped_column(String(3), nullable=False)
    destination: Mapped[str] = mapped_column(String(3), nullable=False)
    flight_date: Mapped[date] = mapped_column(Date, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    seats_available: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    flight_id: Mapped[str] = mapped_column(ForeignKey("flights.flight_id"), nullable=False, index=True)
    passenger_name: Mapped[str] = mapped_column(String(200), nullable=False)
    fare_class: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CONFIRMED")
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
