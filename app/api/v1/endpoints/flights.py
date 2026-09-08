from datetime import date
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.crud.crud_flight import (
    buscar_vuelos_directos,
    buscar_vuelos_con_escala,
    obtener_instancia_por_id,
)
from app.schemas.flight import (
    ItinerarioResponse,
    InstanciaVueloSimpleResponse,
    TarifaInfo,
)
from app.schemas.common import ClaseAsientoEnum

router = APIRouter()


def mapear_instancia_a_schema(instancia) -> InstanciaVueloSimpleResponse:
    tarifas_dto = [
        TarifaInfo(
            id_tarifa=pv.tarifa.id_tarifa,
            clase=ClaseAsientoEnum(pv.tarifa.clase),
            tipo_regla=pv.tarifa.tipo_regla,
            porcentaje_reembolso=pv.tarifa.porcentaje_reembolso,
            precio_base=pv.precio_base,
        )
        for pv in instancia.precios
    ]
    return InstanciaVueloSimpleResponse(
        id_instancia_vuelo=instancia.id_instancia_vuelo,
        id_vuelo_programado=instancia.id_vuelo_programado,
        id_aeropuerto_origen=instancia.vuelo_programado.ruta.id_aeropuerto_origen,
        id_aeropuerto_destino=instancia.vuelo_programado.ruta.id_aeropuerto_destino,
        nombre_origen=instancia.vuelo_programado.ruta.aeropuerto_origen.nombre if instancia.vuelo_programado.ruta.aeropuerto_origen else "",
        nombre_destino=instancia.vuelo_programado.ruta.aeropuerto_destino.nombre if instancia.vuelo_programado.ruta.aeropuerto_destino else "",
        fecha_salida=instancia.fecha_salida,
        hora_salida=instancia.vuelo_programado.hora_salida_programada,
        hora_llegada=instancia.vuelo_programado.hora_llegada_programada,
        asientos_disponibles_eco=instancia.asientos_disponibles_eco,
        asientos_disponibles_biz=instancia.asientos_disponibles_biz,
        estado=instancia.estado,
        tarifas=tarifas_dto,
    )


@router.get("/search", response_model=List[ItinerarioResponse], tags=["Vuelos"])
def buscar_vuelos(
    origen: str = Query(..., min_length=3, max_length=3, description="IATA Origen ej: BOG"),
    destino: str = Query(..., min_length=3, max_length=3, description="IATA Destino ej: MDE"),
    fecha_salida: date = Query(..., description="Fecha de salida (YYYY-MM-DD)"),
    pasajeros: int = Query(1, ge=1, le=10, description="Número de pasajeros"),
    clase: Optional[ClaseAsientoEnum] = Query(None, description="Económica o Ejecutiva"),
    db: Session = Depends(get_db),
):
    """
    Búsqueda de vuelos por origen, destino y fecha, retornando itinerarios directos y con hasta 1 escala (RF-01, RNF-01).
    """
    clase_str = clase.value if clase else None
    resultados: List[ItinerarioResponse] = []

    # 1. Búsqueda de itinerarios directos
    vuelos_directos = buscar_vuelos_directos(
        db, origen=origen, destino=destino, fecha=fecha_salida, pasajeros=pasajeros, clase=clase_str
    )
    for v in vuelos_directos:
        vuelo_dto = mapear_instancia_a_schema(v)
        # Calcular precio base mínimo estimado
        precio_est = min([t.precio_base for t in vuelo_dto.tarifas], default=Decimal("0.00")) * pasajeros
        resultados.append(
            ItinerarioResponse(
                tipo="Directo",
                escalas_count=0,
                trayectos=[vuelo_dto],
                precio_total_estimado=precio_est,
            )
        )

    # 2. Búsqueda de itinerarios con escala
    vuelos_escala = buscar_vuelos_con_escala(
        db, origen=origen, destino=destino, fecha=fecha_salida, pasajeros=pasajeros, clase=clase_str
    )
    for v1, v2 in vuelos_escala:
        dto1 = mapear_instancia_a_schema(v1)
        dto2 = mapear_instancia_a_schema(v2)
        p1 = min([t.precio_base for t in dto1.tarifas], default=Decimal("0.00"))
        p2 = min([t.precio_base for t in dto2.tarifas], default=Decimal("0.00"))
        precio_total = (p1 + p2) * pasajeros
        resultados.append(
            ItinerarioResponse(
                tipo="Con Escala",
                escalas_count=1,
                trayectos=[dto1, dto2],
                precio_total_estimado=precio_total,
            )
        )

    return resultados


@router.get("/{id_instancia}", response_model=InstanciaVueloSimpleResponse, tags=["Vuelos"])
def obtener_detalle_vuelo(id_instancia: int, db: Session = Depends(get_db)):
    """
    Consulta información detallada de una instancia de vuelo e inventario de asientos.
    """
    instancia = obtener_instancia_por_id(db, id_instancia)
    if not instancia:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instancia de vuelo {id_instancia} no encontrada",
        )
    return mapear_instancia_a_schema(instancia)

