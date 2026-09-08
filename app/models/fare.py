from decimal import Decimal
from typing import List, TYPE_CHECKING
from sqlalchemy import Integer, String, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.flight import InstanciaVuelo
    from app.models.reservation import DetalleReserva


class Tarifa(Base):
    __tablename__ = "tarifas"

    id_tarifa: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    clase: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Económica / Ejecutiva"
    )
    tipo_regla: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Promocional / Flexible"
    )
    porcentaje_reembolso: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0.00
    )

    # Relaciones
    precios_vuelo: Mapped[List["PrecioVuelo"]] = relationship(
        "PrecioVuelo", back_populates="tarifa"
    )
    detalles_reserva: Mapped[List["DetalleReserva"]] = relationship(
        "DetalleReserva", back_populates="tarifa"
    )


class PrecioVuelo(Base):
    __tablename__ = "precios_vuelo"

    id_precio: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id_instancia_vuelo: Mapped[int] = mapped_column(
        Integer, ForeignKey("instancias_vuelo.id_instancia_vuelo"), nullable=False
    )
    id_tarifa: Mapped[int] = mapped_column(
        Integer, ForeignKey("tarifas.id_tarifa"), nullable=False
    )
    precio_base: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    # Relaciones
    instancia_vuelo: Mapped["InstanciaVuelo"] = relationship(
        "InstanciaVuelo", back_populates="precios"
    )
    tarifa: Mapped["Tarifa"] = relationship(
        "Tarifa", back_populates="precios_vuelo"
    )

