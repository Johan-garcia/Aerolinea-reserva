from datetime import datetime, time, date
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.common import ClaseAsientoEnum, TipoReglaTarifaEnum


class FlightSearchQuery(BaseModel):
    origen: str = Field(..., min_length=3, max_length=3, description="Código IATA origen, ej: BOG")
    destino: str = Field(..., min_length=3, max_length=3, description="Código IATA destino, ej: MDE")
    fecha_salida: date = Field(..., description="Fecha de salida requerida (YYYY-MM-DD)")
    fecha_retorno: Optional[date] = Field(None, description="Fecha de retorno opcional (YYYY-MM-DD)")
    pasajeros: int = Field(1, ge=1, le=10, description="Número de pasajeros a reservar")
    clase: Optional[ClaseAsientoEnum] = Field(None, description="Económica o Ejecutiva")


class TarifaInfo(BaseModel):
    id_tarifa: int
    clase: ClaseAsientoEnum
    tipo_regla: TipoReglaTarifaEnum
    porcentaje_reembolso: Decimal
    precio_base: Decimal

    model_config = ConfigDict(from_attributes=True)


class InstanciaVueloSimpleResponse(BaseModel):
    id_instancia_vuelo: int
    id_vuelo_programado: str
    id_aeropuerto_origen: str
    id_aeropuerto_destino: str
    nombre_origen: str
    nombre_destino: str
    fecha_salida: datetime
    hora_salida: time
    hora_llegada: time
    asientos_disponibles_eco: int
    asientos_disponibles_biz: int
    estado: str
    tarifas: List[TarifaInfo] = []

    model_config = ConfigDict(from_attributes=True)


class ItinerarioResponse(BaseModel):
    tipo: str = Field(..., description="Directo o Con Escala")
    escalas_count: int = Field(0, description="0 para directo, 1 o 2 para escalas")
    trayectos: List[InstanciaVueloSimpleResponse]
    precio_total_estimado: Decimal

