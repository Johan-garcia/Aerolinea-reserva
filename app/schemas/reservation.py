from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.common import ClaseAsientoEnum, EstadoReservaEnum
from app.schemas.passenger import PasajeroCreate, PasajeroResponse
from app.schemas.payment import PagoCreate, PagoResponse


class DetalleReservaItemCreate(BaseModel):
    id_instancia_vuelo: int = Field(..., description="ID de la instancia de vuelo")
    clase: ClaseAsientoEnum = Field(..., description="Económica o Ejecutiva")
    id_tarifa: int = Field(..., description="ID de la tarifa seleccionada")
    pasajero: PasajeroCreate = Field(..., description="Datos del pasajero asignado al trayecto")
    id_asiento: Optional[int] = Field(None, description="Opcional hasta el check-in")


class ReservaCreate(BaseModel):
    pasajero_comprador: PasajeroCreate = Field(..., description="Datos del pasajero comprador principal")
    codigo_api_key_agencia: Optional[str] = Field(
        None, description="API Key de agencia aliada (si aplica canal B2B)"
    )
    trayectos: List[DetalleReservaItemCreate] = Field(
        ..., min_length=1, description="Lista de trayectos del itinerario (vuelo directo o con escalas)"
    )
    pago: PagoCreate = Field(..., description="Información de pago para confirmación atómica")


class DetalleReservaResponse(BaseModel):
    id_detalle: int
    id_instancia_vuelo: int
    id_vuelo_programado: str
    origen: str
    destino: str
    fecha_salida: datetime
    pasajero: PasajeroResponse
    id_asiento: Optional[int] = None
    numero_asiento: Optional[str] = None
    clase: str
    precio_aplicado: Decimal
    estado_trayecto: str

    model_config = ConfigDict(from_attributes=True)


class ReservaResponse(BaseModel):
    id_reserva: int
    codigo_pnr: str
    fecha_creacion: datetime
    estado: EstadoReservaEnum
    monto_total: Decimal
    pasajero_comprador: PasajeroResponse
    nombre_agencia: Optional[str] = None
    detalles: List[DetalleReservaResponse] = []
    pagos: List[PagoResponse] = []

    model_config = ConfigDict(from_attributes=True)


class ReservaConsultaQuery(BaseModel):
    codigo_pnr: str = Field(..., min_length=5, max_length=10, description="Código PNR de la reserva")
    numero_documento: str = Field(..., description="Número de documento del comprador")

