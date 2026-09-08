from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.schemas.common import MetodoPagoEnum, EstadoPagoEnum


class PagoBase(BaseModel):
    metodo_pago: MetodoPagoEnum
    monto: Decimal


class PagoCreate(BaseModel):
    metodo_pago: MetodoPagoEnum
    id_transaccion_proveedor: Optional[str] = None


class PagoResponse(PagoBase):
    id_pago: int
    id_reserva: int
    fecha_pago: datetime
    id_transaccion_proveedor: str
    estado_pago: EstadoPagoEnum

    model_config = ConfigDict(from_attributes=True)

