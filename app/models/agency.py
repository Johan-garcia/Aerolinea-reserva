from decimal import Decimal
from typing import List, TYPE_CHECKING
from sqlalchemy import Integer, String, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.reservation import Reserva


class AgenciaAliada(Base):
    __tablename__ = "agencias_aliadas"

    id_agencia: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    nombre_agencia: Mapped[str] = mapped_column(String(150), nullable=False)
    codigo_api_key: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False, comment="API Key para autenticación B2B"
    )
    porcentaje_comision: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0.00
    )

    # Relaciones
    reservas: Mapped[List["Reserva"]] = relationship(
        "Reserva", back_populates="agencia"
    )

