from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import Integer, String, Numeric, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.reservation import Reserva


class Pago(Base):
    __tablename__ = "pagos"

    id_pago: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id_reserva: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservas.id_reserva"), nullable=False
    )
    fecha_pago: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    monto: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    metodo_pago: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Tarjeta, PSE, Transferencia, etc."
    )
    id_transaccion_proveedor: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Identificador UUID retornado por la pasarela de pago",
    )
    estado_pago: Mapped[str] = mapped_column(
        String(50),
        default="Aprobado",
        comment="Valores: Aprobado, Rechazado, Pendiente",
    )

    # Relaciones
    reserva: Mapped["Reserva"] = relationship(
        "Reserva", back_populates="pagos"
    )

