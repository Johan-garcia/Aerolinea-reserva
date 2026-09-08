from typing import List, TYPE_CHECKING
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.seat import Asiento
    from app.models.flight import InstanciaVuelo


class Avion(Base):
    __tablename__ = "aviones"

    id_avion: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    modelo: Mapped[str] = mapped_column(String(100), nullable=False)
    capacidad_total: Mapped[int] = mapped_column(Integer, nullable=False)
    filas: Mapped[int] = mapped_column(Integer, nullable=False)
    columnas: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relaciones
    asientos: Mapped[List["Asiento"]] = relationship(
        "Asiento", back_populates="avion", cascade="all, delete-orphan"
    )
    instancias_vuelo: Mapped[List["InstanciaVuelo"]] = relationship(
        "InstanciaVuelo", back_populates="avion"
    )

