from datetime import datetime
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import (
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.passenger import Pasajero
    from app.models.agency import AgenciaAliada
    from app.models.flight import InstanciaVuelo
    from app.models.seat import Asiento
    from app.models.fare import Tarifa
    from app.models.payment import Pago
    from app.models.audit import AuditoriaReserva


class Reserva(Base):
    __tablename__ = "reservas"

    id_reserva: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    codigo_pnr: Mapped[str] = mapped_column(
        String(10),
        unique=True,
        index=True,
        nullable=False,
        comment="Código PNR alfanumérico ej: X7K9LP",
    )
    id_pasajero_comprador: Mapped[int] = mapped_column(
        Integer, ForeignKey("pasajeros.id_pasajero"), nullable=False
    )
    id_agencia: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("agencias_aliadas.id_agencia"),
        nullable=True,
        comment="Nullable si es venta directa en la web",
    )
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    estado: Mapped[str] = mapped_column(
        String(50),
        default="Pendiente",
        comment="Valores: Pendiente, Confirmada, Cancelada",
    )
    monto_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0.00
    )

    # Relaciones
    pasajero_comprador: Mapped["Pasajero"] = relationship(
        "Pasajero", back_populates="reservas_compradas"
    )
    agencia: Mapped[Optional["AgenciaAliada"]] = relationship(
        "AgenciaAliada", back_populates="reservas"
    )
    detalles: Mapped[List["DetalleReserva"]] = relationship(
        "DetalleReserva", back_populates="reserva", cascade="all, delete-orphan"
    )
    pagos: Mapped[List["Pago"]] = relationship(
        "Pago", back_populates="reserva", cascade="all, delete-orphan"
    )
    auditorias: Mapped[List["AuditoriaReserva"]] = relationship(
        "AuditoriaReserva", back_populates="reserva", cascade="all, delete-orphan"
    )


class DetalleReserva(Base):
    __tablename__ = "detalles_reserva"

    id_detalle: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id_reserva: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservas.id_reserva"), nullable=False
    )
    id_instancia_vuelo: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("instancias_vuelo.id_instancia_vuelo"),
        nullable=False,
    )
    id_pasajero: Mapped[int] = mapped_column(
        Integer, ForeignKey("pasajeros.id_pasajero"), nullable=False
    )
    id_asiento: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("asientos.id_asiento"),
        nullable=True,
        comment="Nullable hasta que el pasajero realice el check-in",
    )
    id_tarifa: Mapped[int] = mapped_column(
        Integer, ForeignKey("tarifas.id_tarifa"), nullable=False
    )
    precio_aplicado: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    estado_trayecto: Mapped[str] = mapped_column(
        String(50), default="Confirmado", comment="Confirmado, Cancelado, Volado"
    )

    # Relaciones
    reserva: Mapped["Reserva"] = relationship(
        "Reserva", back_populates="detalles"
    )
    instancia_vuelo: Mapped["InstanciaVuelo"] = relationship(
        "InstanciaVuelo", back_populates="detalles_reserva"
    )
    pasajero: Mapped["Pasajero"] = relationship(
        "Pasajero", back_populates="trayectos"
    )
    asiento: Mapped[Optional["Asiento"]] = relationship(
        "Asiento", back_populates="detalles_reserva"
    )
    tarifa: Mapped["Tarifa"] = relationship(
        "Tarifa", back_populates="detalles_reserva"
    )

