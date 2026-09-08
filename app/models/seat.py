from datetime import datetime
from typing import List, TYPE_CHECKING
from sqlalchemy import Integer, String, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.airplane import Avion
    from app.models.reservation import DetalleReserva


class Asiento(Base):
    __tablename__ = "asientos"

    id_asiento: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id_avion: Mapped[int] = mapped_column(
        Integer, ForeignKey("aviones.id_avion"), nullable=False
    )
    numero_asiento: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="Ej: 12A, 1B"
    )
    clase: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Económica / Ejecutiva"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Auditoría temporal del asiento",
    )

    __table_args__ = (
        UniqueConstraint("id_avion", "numero_asiento", name="uq_avion_asiento"),
    )

    # Relaciones
    avion: Mapped["Avion"] = relationship(
        "Avion", back_populates="asientos"
    )
    detalles_reserva: Mapped[List["DetalleReserva"]] = relationship(
        "DetalleReserva", back_populates="asiento"
    )

