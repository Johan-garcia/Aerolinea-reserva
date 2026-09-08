from datetime import datetime, time
from typing import List, TYPE_CHECKING
from sqlalchemy import (
    Integer,
    String,
    Time,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.route import Ruta
    from app.models.airplane import Avion
    from app.models.fare import PrecioVuelo
    from app.models.reservation import DetalleReserva


class VueloProgramado(Base):
    __tablename__ = "vuelos_programados"

    id_vuelo_programado: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="Identificador de vuelo ej: AV9301"
    )
    id_ruta: Mapped[int] = mapped_column(
        Integer, ForeignKey("rutas.id_ruta"), nullable=False
    )
    hora_salida_programada: Mapped[time] = mapped_column(Time, nullable=False)
    hora_llegada_programada: Mapped[time] = mapped_column(Time, nullable=False)

    # Relaciones
    ruta: Mapped["Ruta"] = relationship(
        "Ruta", back_populates="vuelos_programados"
    )
    instancias: Mapped[List["InstanciaVuelo"]] = relationship(
        "InstanciaVuelo", back_populates="vuelo_programado"
    )


class InstanciaVuelo(Base):
    __tablename__ = "instancias_vuelo"

    id_instancia_vuelo: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id_vuelo_programado: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("vuelos_programados.id_vuelo_programado"),
        nullable=False,
    )
    id_avion: Mapped[int] = mapped_column(
        Integer, ForeignKey("aviones.id_avion"), nullable=False
    )
    fecha_salida: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    asientos_disponibles_eco: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Control de inventario clase Económica"
    )
    asientos_disponibles_biz: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Control de inventario clase Ejecutiva"
    )
    estado: Mapped[str] = mapped_column(
        String(50),
        default="Programado",
        comment="Valores: Programado, En Vuelo, Cancelado, Completado",
    )

    # Restricciones a nivel de motor de base de datos para impedir sobreventa (0% oversell)
    __table_args__ = (
        CheckConstraint(
            "asientos_disponibles_eco >= 0",
            name="chk_asientos_eco_no_negativo",
        ),
        CheckConstraint(
            "asientos_disponibles_biz >= 0",
            name="chk_asientos_biz_no_negativo",
        ),
        Index(
            "ix_instancia_vuelo_busqueda",
            "id_vuelo_programado",
            "fecha_salida",
            "estado",
        ),
    )

    # Relaciones
    vuelo_programado: Mapped["VueloProgramado"] = relationship(
        "VueloProgramado", back_populates="instancias"
    )
    avion: Mapped["Avion"] = relationship(
        "Avion", back_populates="instancias_vuelo"
    )
    precios: Mapped[List["PrecioVuelo"]] = relationship(
        "PrecioVuelo",
        back_populates="instancia_vuelo",
        cascade="all, delete-orphan",
    )
    detalles_reserva: Mapped[List["DetalleReserva"]] = relationship(
        "DetalleReserva", back_populates="instancia_vuelo"
    )

