from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Integer, String, DateTime, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.reservation import Reserva


class AuditoriaReserva(Base):
    __tablename__ = "auditorias_reserva"

    id_auditoria: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id_reserva: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservas.id_reserva"), nullable=False
    )
    accion: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="CREACION, CANCELACION, MODIFICACION, CAMBIO_ESTADO",
    )
    estado_anterior: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    estado_nuevo: Mapped[str] = mapped_column(String(50), nullable=False)
    fecha_hora_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Marca de tiempo UTC inmutable (RNF-05)",
    )
    responsable_tipo: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="USUARIO",
        comment="Valores: USUARIO, AGENCIA_API_KEY, SISTEMA",
    )
    responsable_identificador: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Identificador del usuario o API Key responsable",
    )

    __table_args__ = (
        Index("ix_auditoria_reserva_fecha", "id_reserva", "fecha_hora_utc"),
    )

    # Relaciones
    reserva: Mapped["Reserva"] = relationship(
        "Reserva", back_populates="auditorias"
    )

