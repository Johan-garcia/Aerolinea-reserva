from datetime import date, datetime, time
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.models.flight import InstanciaVuelo, VueloProgramado
from app.models.route import Ruta
from app.models.fare import PrecioVuelo, Tarifa
from app.models.airport import Aeropuerto


def obtener_instancia_por_id(db: Session, id_instancia: int) -> Optional[InstanciaVuelo]:
    return (
        db.query(InstanciaVuelo)
        .options(
            joinedload(InstanciaVuelo.vuelo_programado).joinedload(VueloProgramado.ruta),
            joinedload(InstanciaVuelo.precios).joinedload(PrecioVuelo.tarifa),
        )
        .filter(InstanciaVuelo.id_instancia_vuelo == id_instancia)
        .first()
    )


def buscar_vuelos_directos(
    db: Session,
    origen: str,
    destino: Optional[str] = None,
    fecha: Optional[date] = None,
    pasajeros: int = 1,
    clase: Optional[str] = None,
) -> List[InstanciaVuelo]:
    """
    Búsqueda optimizada de vuelos directos para una fecha y ruta específica (RF-01).
    Filtra por cupos disponibles en la clase solicitada.
    """
    if fecha is None:
        fecha = date.today()

    inicio_dia = datetime.combine(fecha, time.min)
    fin_dia = datetime.combine(fecha, time.max)

    query = (
        db.query(InstanciaVuelo)
        .join(InstanciaVuelo.vuelo_programado)
        .join(VueloProgramado.ruta)
        .options(
            joinedload(InstanciaVuelo.vuelo_programado).joinedload(VueloProgramado.ruta).joinedload(Ruta.aeropuerto_origen),
            joinedload(InstanciaVuelo.vuelo_programado).joinedload(VueloProgramado.ruta).joinedload(Ruta.aeropuerto_destino),
            joinedload(InstanciaVuelo.precios).joinedload(PrecioVuelo.tarifa),
        )
        .filter(
            Ruta.id_aeropuerto_origen == origen.upper(),
            InstanciaVuelo.fecha_salida >= inicio_dia,
            InstanciaVuelo.fecha_salida <= fin_dia,
            InstanciaVuelo.estado == "Programado",
        )
    )

    if destino and destino != "%":
        query = query.filter(Ruta.id_aeropuerto_destino == destino.upper())

    if clase == "Económica":
        query = query.filter(InstanciaVuelo.asientos_disponibles_eco >= pasajeros)
    elif clase == "Ejecutiva":
        query = query.filter(InstanciaVuelo.asientos_disponibles_biz >= pasajeros)
    else:
        # Al menos una clase debe tener disponibilidad suficiente
        query = query.filter(
            (InstanciaVuelo.asientos_disponibles_eco >= pasajeros)
            | (InstanciaVuelo.asientos_disponibles_biz >= pasajeros)
        )

    return query.order_by(InstanciaVuelo.fecha_salida).all()


def buscar_vuelos_con_escala(
    db: Session,
    origen: str,
    destino: str,
    fecha: date,
    pasajeros: int = 1,
    clase: Optional[str] = None,
) -> List[Tuple[InstanciaVuelo, InstanciaVuelo]]:
    """
    Búsqueda de itinerarios con 1 escala (RF-01, RNF-01).
    Encuentra combinaciones (Vuelo 1: Origen -> Escala) y (Vuelo 2: Escala -> Destino)
    donde el tiempo de conexión sea de mínimo 45 minutos y máximo 8 horas.
    """
    # Tramo 1
    tramos_1 = buscar_vuelos_directos(
        db, origen=origen, destino="%", fecha=fecha, pasajeros=pasajeros, clase=clase
    )
    # Excluir vuelos que van directo al destino en el tramo 1
    tramos_1 = [t for t in tramos_1 if t.vuelo_programado.ruta.id_aeropuerto_destino != destino.upper()]

    itinerarios_escala = []
    for v1 in tramos_1:
        escala_iata = v1.vuelo_programado.ruta.id_aeropuerto_destino
        # Tramo 2 saliendo desde la escala hacia el destino final
        tramos_2 = buscar_vuelos_directos(
            db, origen=escala_iata, destino=destino, fecha=fecha, pasajeros=pasajeros, clase=clase
        )
        for v2 in tramos_2:
            # Validar que v2 salga después de v1 con una conexión válida
            if v2.fecha_salida > v1.fecha_salida:
                diferencia_minutos = (v2.fecha_salida - v1.fecha_salida).total_seconds() / 60
                if 45 <= diferencia_minutos <= 480:  # entre 45 min y 8 horas
                    itinerarios_escala.append((v1, v2))

    return itinerarios_escala

