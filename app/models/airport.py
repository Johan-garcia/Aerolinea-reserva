from typing import List, TYPE_CHECKING
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.route import Ruta


class Aeropuerto(Base):
    __tablename__ = "aeropuertos"

    id_aeropuerto: Mapped[str] = mapped_column(
        String(3), primary_key=True, comment="Código IATA: BOG, MDE, etc."
    )
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    ciudad: Mapped[str] = mapped_column(String(100), nullable=False)
    pais: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relaciones con Ruta
    rutas_origen: Mapped[List["Ruta"]] = relationship(
        "Ruta",
        foreign_keys="[Ruta.id_aeropuerto_origen]",
        back_populates="aeropuerto_origen",
    )
    rutas_destino: Mapped[List["Ruta"]] = relationship(
        "Ruta",
        foreign_keys="[Ruta.id_aeropuerto_destino]",
        back_populates="aeropuerto_destino",
    )

