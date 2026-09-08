from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.crud.crud_reservation import (
    crear_reserva_con_control_concurrencia,
    consultar_reserva_por_pnr_y_documento,
    cancelar_reserva,
)
from app.schemas.reservation import (
    ReservaCreate,
    ReservaResponse,
    DetalleReservaResponse,
)
from app.schemas.passenger import PasajeroResponse
from app.schemas.payment import PagoResponse
from app.schemas.common import EstadoReservaEnum, EstadoPagoEnum

router = APIRouter()


def mapear_reserva_a_response(reserva) -> ReservaResponse:
    detalles_dto = []
    for d in reserva.detalles:
        origen = d.instancia_vuelo.vuelo_programado.ruta.id_aeropuerto_origen if d.instancia_vuelo else ""
        destino = d.instancia_vuelo.vuelo_programado.ruta.id_aeropuerto_destino if d.instancia_vuelo else ""
        num_vuelo = d.instancia_vuelo.vuelo_programado.id_vuelo_programado if d.instancia_vuelo else ""
        fecha_salida = d.instancia_vuelo.fecha_salida if d.instancia_vuelo else None
        num_asiento = d.asiento.numero_asiento if d.asiento else None

        detalles_dto.append(
            DetalleReservaResponse(
                id_detalle=d.id_detalle,
                id_instancia_vuelo=d.id_instancia_vuelo,
                id_vuelo_programado=num_vuelo,
                origen=origen,
                destino=destino,
                fecha_salida=fecha_salida,
                pasajero=PasajeroResponse.model_validate(d.pasajero),
                id_asiento=d.id_asiento,
                numero_asiento=num_asiento,
                clase=d.tarifa.clase,
                precio_aplicado=d.precio_aplicado,
                estado_trayecto=d.estado_trayecto,
            )
        )

    pagos_dto = [
        PagoResponse(
            id_pago=p.id_pago,
            id_reserva=p.id_reserva,
            fecha_pago=p.fecha_pago,
            monto=p.monto,
            metodo_pago=p.metodo_pago,
            id_transaccion_proveedor=p.id_transaccion_proveedor,
            estado_pago=EstadoPagoEnum(p.estado_pago),
        )
        for p in reserva.pagos
    ]

    return ReservaResponse(
        id_reserva=reserva.id_reserva,
        codigo_pnr=reserva.codigo_pnr,
        fecha_creacion=reserva.fecha_creacion,
        estado=EstadoReservaEnum(reserva.estado),
        monto_total=reserva.monto_total,
        pasajero_comprador=PasajeroResponse.model_validate(reserva.pasajero_comprador),
        nombre_agencia=reserva.agencia.nombre_agencia if reserva.agencia else None,
        detalles=detalles_dto,
        pagos=pagos_dto,
    )


@router.post(
    "",
    response_model=ReservaResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Reservas"],
)
def crear_reserva(reserva_in: ReservaCreate, db: Session = Depends(get_db)):
    """
    Crea una reserva multitrayecto con control estricto de concurrencia (bloqueo pesimista)
    para evitar sobreventa (0% overselling) y pago atómico (RF-02, RF-04, RNF-02).
    """
    reserva = crear_reserva_con_control_concurrencia(db, reserva_in)
    return mapear_reserva_a_response(reserva)


@router.get("/{codigo_pnr}", response_model=ReservaResponse, tags=["Reservas"])
def consultar_reserva(
    codigo_pnr: str,
    numero_documento: str = Query(..., description="Número de documento del comprador"),
    db: Session = Depends(get_db),
):
    """
    Consulta una reserva por código PNR y documento de identidad del comprador (RF-05).
    """
    reserva = consultar_reserva_por_pnr_y_documento(db, codigo_pnr, numero_documento)
    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró reserva con PNR {codigo_pnr} para el documento indicado",
        )
    return mapear_reserva_a_response(reserva)


@router.post("/{codigo_pnr}/cancel", response_model=ReservaResponse, tags=["Reservas"])
def cancelar_reserva_endpoint(
    codigo_pnr: str,
    numero_documento: str = Query(..., description="Número de documento del comprador"),
    db: Session = Depends(get_db),
):
    """
    Cancela una reserva, libera los asientos al inventario y genera registro inmutable de auditoría (RF-05, RNF-05).
    """
    reserva = cancelar_reserva(db, codigo_pnr, numero_documento)
    return mapear_reserva_a_response(reserva)

