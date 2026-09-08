import string
import random
import uuid
from decimal import Decimal
from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.models.flight import InstanciaVuelo
from app.models.passenger import Pasajero
from app.models.agency import AgenciaAliada
from app.models.fare import PrecioVuelo
from app.models.reservation import Reserva, DetalleReserva
from app.models.payment import Pago
from app.models.audit import AuditoriaReserva
from app.schemas.reservation import ReservaCreate
from app.schemas.common import EstadoReservaEnum, EstadoPagoEnum


def generar_codigo_pnr(db: Session, longitud: int = 6) -> str:
    """
    Genera un código PNR alfanumérico único (ej. X7K9LP).
    """
    caracteres = string.ascii_uppercase + "23456789"  # excluye 0 y 1 para evitar confusión visual
    for _ in range(10):
        pnr = "".join(random.choices(caracteres, k=longitud))
        existe = db.query(Reserva).filter(Reserva.codigo_pnr == pnr).first()
        if not existe:
            return pnr
    # Fallback con uuid
    return uuid.uuid4().hex[:longitud].upper()


def obtener_o_crear_pasajero(db: Session, pasajero_data) -> Pasajero:
    pasajero = (
        db.query(Pasajero)
        .filter(
            Pasajero.tipo_documento == pasajero_data.tipo_documento,
            Pasajero.numero_documento == pasajero_data.numero_documento,
        )
        .first()
    )
    if not pasajero:
        pasajero = Pasajero(
            tipo_documento=pasajero_data.tipo_documento,
            numero_documento=pasajero_data.numero_documento,
            nombres=pasajero_data.nombres,
            apellidos=pasajero_data.apellidos,
            email=pasajero_data.email,
            telefono=pasajero_data.telefono,
        )
        db.add(pasajero)
        db.flush()
    return pasajero


def crear_reserva_con_control_concurrencia(
    db: Session, reserva_in: ReservaCreate
) -> Reserva:
    """
    Crea una reserva multitrayecto garantizando 0% sobreventa mediante
    bloqueo pesimista (SELECT ... FOR UPDATE) a nivel de base de datos relacional (RNF-02, RF-02, RF-04).
    """
    # 1. Validar agencia aliada si se envió API Key
    agencia_id = None
    responsable_tipo = "USUARIO"
    responsable_id = None
    if reserva_in.codigo_api_key_agencia:
        agencia = (
            db.query(AgenciaAliada)
            .filter(AgenciaAliada.codigo_api_key == reserva_in.codigo_api_key_agencia)
            .first()
        )
        if not agencia:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key de agencia aliada no válida o inactiva",
            )
        agencia_id = agencia.id_agencia
        responsable_tipo = "AGENCIA_API_KEY"
        responsable_id = agencia.nombre_agencia

    # 2. Obtener o registrar pasajero comprador
    comprador = obtener_o_crear_pasajero(db, reserva_in.pasajero_comprador)
    if not responsable_id:
        responsable_id = f"DOC:{comprador.tipo_documento}-{comprador.numero_documento}"

    # 3. Ordenar IDs de instancias de vuelo para prevenir bloqueos mutuos (deadlocks)
    instancia_ids = sorted(list(set(t.id_instancia_vuelo for t in reserva_in.trayectos)))

    # 4. Bloqueo pesimista: SELECT ... FOR UPDATE sobre las instancias de vuelo
    instancias_bloqueadas = {}
    for i_id in instancia_ids:
        instancia = (
            db.query(InstanciaVuelo)
            .filter(InstanciaVuelo.id_instancia_vuelo == i_id)
            .with_for_update()
            .first()
        )
        if not instancia:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"La instancia de vuelo con ID {i_id} no existe",
            )
        if instancia.estado != "Programado":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El vuelo {instancia.id_vuelo_programado} no está disponible para reservas (Estado: {instancia.estado})",
            )
        instancias_bloqueadas[i_id] = instancia

    # 5. Validar disponibilidad y descontar inventario en la misma transacción atómica
    detalles_a_crear = []
    monto_total = Decimal("0.00")

    for item in reserva_in.trayectos:
        instancia = instancias_bloqueadas[item.id_instancia_vuelo]

        # Comprobar cupo en la clase solicitada
        if item.clase == "Económica":
            if instancia.asientos_disponibles_eco < 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"No hay asientos disponibles en clase Económica para el vuelo "
                        f"{instancia.id_vuelo_programado} en fecha {instancia.fecha_salida}"
                    ),
                )
            # Descuento atómico de inventario
            instancia.asientos_disponibles_eco -= 1
        elif item.clase == "Ejecutiva":
            if instancia.asientos_disponibles_biz < 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"No hay asientos disponibles en clase Ejecutiva para el vuelo "
                        f"{instancia.id_vuelo_programado} en fecha {instancia.fecha_salida}"
                    ),
                )
            # Descuento atómico de inventario
            instancia.asientos_disponibles_biz -= 1
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Clase de asiento '{item.clase}' no válida",
            )

        # Consultar precio aplicable
        precio_vuelo = (
            db.query(PrecioVuelo)
            .filter(
                PrecioVuelo.id_instancia_vuelo == item.id_instancia_vuelo,
                PrecioVuelo.id_tarifa == item.id_tarifa,
            )
            .first()
        )
        if not precio_vuelo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"No existe tarifa configurada para la instancia {item.id_instancia_vuelo} "
                    f"y tarifa {item.id_tarifa}"
                ),
            )

        pasajero_trayecto = obtener_o_crear_pasajero(db, item.pasajero)
        precio_aplicado = precio_vuelo.precio_base
        monto_total += precio_aplicado

        detalles_a_crear.append(
            {
                "id_instancia_vuelo": item.id_instancia_vuelo,
                "id_pasajero": pasajero_trayecto.id_pasajero,
                "id_tarifa": item.id_tarifa,
                "id_asiento": item.id_asiento,
                "precio_aplicado": precio_aplicado,
            }
        )

    # 6. Generar PNR único y crear la entidad Reserva
    codigo_pnr = generar_codigo_pnr(db)
    reserva = Reserva(
        codigo_pnr=codigo_pnr,
        id_pasajero_comprador=comprador.id_pasajero,
        id_agencia=agencia_id,
        estado=EstadoReservaEnum.CONFIRMADA.value,
        monto_total=monto_total,
    )
    db.add(reserva)
    db.flush()

    # 7. Crear los detalles de la reserva (trayectos)
    for d in detalles_a_crear:
        detalle = DetalleReserva(
            id_reserva=reserva.id_reserva,
            id_instancia_vuelo=d["id_instancia_vuelo"],
            id_pasajero=d["id_pasajero"],
            id_tarifa=d["id_tarifa"],
            id_asiento=d["id_asiento"],
            precio_aplicado=d["precio_aplicado"],
            estado_trayecto="Confirmado",
        )
        db.add(detalle)

    # 8. Procesamiento atómico del pago (RF-04)
    transaccion_id = reserva_in.pago.id_transaccion_proveedor or str(uuid.uuid4())
    pago = Pago(
        id_reserva=reserva.id_reserva,
        monto=monto_total,
        metodo_pago=reserva_in.pago.metodo_pago.value,
        id_transaccion_proveedor=transaccion_id,
        estado_pago=EstadoPagoEnum.APROBADO.value,
    )
    db.add(pago)

    # 9. Registro inmutable en el historial de auditoría (RNF-05)
    auditoria = AuditoriaReserva(
        id_reserva=reserva.id_reserva,
        accion="CREACION",
        estado_anterior=None,
        estado_nuevo=EstadoReservaEnum.CONFIRMADA.value,
        responsable_tipo=responsable_tipo,
        responsable_identificador=responsable_id,
    )
    db.add(auditoria)

    # Commit atómico de la transacción
    db.commit()
    db.refresh(reserva)
    return reserva


def consultar_reserva_por_pnr_y_documento(
    db: Session, codigo_pnr: str, numero_documento: str
) -> Optional[Reserva]:
    """
    Consulta el estado completo de una reserva validando PNR y documento del comprador (RF-05).
    """
    return (
        db.query(Reserva)
        .join(Reserva.pasajero_comprador)
        .options(
            joinedload(Reserva.pasajero_comprador),
            joinedload(Reserva.agencia),
            joinedload(Reserva.detalles).joinedload(DetalleReserva.instancia_vuelo).joinedload(InstanciaVuelo.vuelo_programado),
            joinedload(Reserva.detalles).joinedload(DetalleReserva.pasajero),
            joinedload(Reserva.detalles).joinedload(DetalleReserva.tarifa),
            joinedload(Reserva.detalles).joinedload(DetalleReserva.asiento),
            joinedload(Reserva.pagos),
        )
        .filter(
            Reserva.codigo_pnr == codigo_pnr.upper(),
            Pasajero.numero_documento == numero_documento,
        )
        .first()
    )


def cancelar_reserva(
    db: Session, codigo_pnr: str, numero_documento: str, motivo: str = "Cancelación por usuario"
) -> Reserva:
    """
    Cancela una reserva, libera los asientos al inventario mediante bloqueo pesimista
    y registra el cambio en el log de auditoría (RF-05, RNF-05).
    """
    reserva = consultar_reserva_por_pnr_y_documento(db, codigo_pnr, numero_documento)
    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reserva no encontrada con los datos suministrados",
        )

    if reserva.estado == EstadoReservaEnum.CANCELADA.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La reserva ya se encuentra cancelada",
        )

    # Bloquear instancias de vuelo y restaurar inventario
    for detalle in reserva.detalles:
        instancia = (
            db.query(InstanciaVuelo)
            .filter(InstanciaVuelo.id_instancia_vuelo == detalle.id_instancia_vuelo)
            .with_for_update()
            .first()
        )
        if instancia:
            if detalle.tarifa.clase == "Económica":
                instancia.asientos_disponibles_eco += 1
            else:
                instancia.asientos_disponibles_biz += 1
            detalle.estado_trayecto = "Cancelado"

    estado_anterior = reserva.estado
    reserva.estado = EstadoReservaEnum.CANCELADA.value

    # Registro de auditoría
    auditoria = AuditoriaReserva(
        id_reserva=reserva.id_reserva,
        accion="CANCELACION",
        estado_anterior=estado_anterior,
        estado_nuevo=EstadoReservaEnum.CANCELADA.value,
        responsable_tipo="USUARIO",
        responsable_identificador=f"DOC:{numero_documento}",
    )
    db.add(auditoria)

    db.commit()
    db.refresh(reserva)
    return reserva

