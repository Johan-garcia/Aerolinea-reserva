from typing import List, TYPE_CHECKING
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.airport import Aeropuerto
    from app.models.flight import VueloProgramado


class Ruta(Base):
    __tablename__ = "rutas"

    id_ruta: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id_aeropuerto_origen: Mapped[str] = mapped_column(
        String(3), ForeignKey("aeropuertos.id_aeropuerto"), nullable=False
    )
    id_aeropuerto_destino: Mapped[str] = mapped_column(
        String(3), ForeignKey("aeropuertos.id_aeropuerto"), nullable=False
    )
    distancia_km: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relaciones
    aeropuerto_origen: Mapped["Aeropuerto"] = relationship(
        "Aeropuerto",
        foreign_keys=[id_aeropuerto_origen],
        back_populates="rutas_origen",
    )
    aeropuerto_destino: Mapped["Aeropuerto"] = relationship(
        "Aeropuerto",
        foreign_keys=[id_aeropuerto_destino],
        back_populates="rutas_destino",
    )
    vuelos_programados: Mapped[List["VueloProgramado"]] = relationship(
        "VueloProgramado", back_populates="ruta"
    )

