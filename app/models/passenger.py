from typing import List, TYPE_CHECKING
from sqlalchemy import Integer, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.reservation import Reserva, DetalleReserva


class Pasajero(Base):
    __tablename__ = "pasajeros"

    id_pasajero: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    tipo_documento: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="CC, CE, PAS, etc."
    )
    numero_documento: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    nombres: Mapped[str] = mapped_column(String(100), nullable=False)
    apellidos: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    telefono: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        Index("ix_pasajero_doc", "tipo_documento", "numero_documento"),
    )

    # Relaciones
    reservas_compradas: Mapped[List["Reserva"]] = relationship(
        "Reserva", back_populates="pasajero_comprador"
    )
    trayectos: Mapped[List["DetalleReserva"]] = relationship(
        "DetalleReserva", back_populates="pasajero"
    )

