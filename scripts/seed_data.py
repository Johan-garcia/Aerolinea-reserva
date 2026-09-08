import sys
from pathlib import Path

# Asegurar que el directorio raíz del proyecto esté en el PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, date, time, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine
from app.models import (
    Base,
    Aeropuerto,
    Ruta,
    Avion,
    Asiento,
    VueloProgramado,
    InstanciaVuelo,
    Tarifa,
    PrecioVuelo,
    AgenciaAliada,
)


def seed():
    print("Creando tablas en la base de datos...")
    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()
    try:
        # 1. Aeropuertos
        if db.query(Aeropuerto).count() == 0:
            print("Insertando aeropuertos...")
            aeropuertos = [
                Aeropuerto(id_aeropuerto="BOG", nombre="El Dorado", ciudad="Bogotá", pais="Colombia"),
                Aeropuerto(id_aeropuerto="MDE", nombre="José María Córdova", ciudad="Medellín", pais="Colombia"),
                Aeropuerto(id_aeropuerto="CLO", nombre="Alfonso Bonilla Aragón", ciudad="Cali", pais="Colombia"),
                Aeropuerto(id_aeropuerto="CTG", nombre="Rafael Núñez", ciudad="Cartagena", pais="Colombia"),
            ]
            db.add_all(aeropuertos)
            db.commit()

        # 2. Rutas
        if db.query(Ruta).count() == 0:
            print("Insertando rutas...")
            rutas = [
                Ruta(id_aeropuerto_origen="BOG", id_aeropuerto_destino="MDE", distancia_km=240),
                Ruta(id_aeropuerto_origen="MDE", id_aeropuerto_destino="CTG", distancia_km=460),
                Ruta(id_aeropuerto_origen="BOG", id_aeropuerto_destino="CTG", distancia_km=650),
                Ruta(id_aeropuerto_origen="CLO", id_aeropuerto_destino="BOG", distancia_km=300),
            ]
            db.add_all(rutas)
            db.commit()

        # 3. Aviones y Asientos
        if db.query(Avion).count() == 0:
            print("Insertando aviones y asientos...")
            a320 = Avion(modelo="Airbus A320", capacidad_total=150, filas=25, columnas=6)
            db.add(a320)
            db.flush()

            asientos = []
            # Filas 1 a 3 Ejecutiva
            for f in range(1, 4):
                for col in ["A", "B", "C", "D"]:
                    asientos.append(Asiento(id_avion=a320.id_avion, numero_asiento=f"{f}{col}", clase="Ejecutiva"))
            # Filas 4 a 25 Económica
            for f in range(4, 26):
                for col in ["A", "B", "C", "D", "E", "F"]:
                    asientos.append(Asiento(id_avion=a320.id_avion, numero_asiento=f"{f}{col}", clase="Económica"))
            db.add_all(asientos)
            db.commit()

        # 4. Tarifas
        if db.query(Tarifa).count() == 0:
            print("Insertando tarifas...")
            tarifas = [
                Tarifa(clase="Económica", tipo_regla="Promocional", porcentaje_reembolso=Decimal("0.00")),
                Tarifa(clase="Económica", tipo_regla="Flexible", porcentaje_reembolso=Decimal("80.00")),
                Tarifa(clase="Ejecutiva", tipo_regla="Flexible", porcentaje_reembolso=Decimal("100.00")),
            ]
            db.add_all(tarifas)
            db.commit()

        # 5. Vuelos Programados
        if db.query(VueloProgramado).count() == 0:
            print("Insertando vuelos programados...")
            vuelos_prog = [
                VueloProgramado(
                    id_vuelo_programado="AV9301",
                    id_ruta=1,  # BOG -> MDE
                    hora_salida_programada=time(8, 0),
                    hora_llegada_programada=time(9, 0),
                ),
                VueloProgramado(
                    id_vuelo_programado="AV9303",
                    id_ruta=2,  # MDE -> CTG (Conexión)
                    hora_salida_programada=time(10, 30),
                    hora_llegada_programada=time(11, 40),
                ),
                VueloProgramado(
                    id_vuelo_programado="AV9305",
                    id_ruta=3,  # BOG -> CTG (Directo)
                    hora_salida_programada=time(14, 0),
                    hora_llegada_programada=time(15, 30),
                ),
            ]
            db.add_all(vuelos_prog)
            db.commit()

        # 6. Instancias de Vuelo
        print("Verificando instancias de vuelo para los próximos 60 días...")
        hoy = date.today()
        avion = db.query(Avion).first()

        tarifas_db = db.query(Tarifa).all()
        t_eco_promo = next(t for t in tarifas_db if t.clase == "Económica" and t.tipo_regla == "Promocional")
        t_eco_flex = next(t for t in tarifas_db if t.clase == "Económica" and t.tipo_regla == "Flexible")
        t_biz_flex = next(t for t in tarifas_db if t.clase == "Ejecutiva" and t.tipo_regla == "Flexible")

        for offset in range(60):
            dia = hoy + timedelta(days=offset)
            inicio_dia = datetime.combine(dia, time.min)
            fin_dia = datetime.combine(dia, time.max)

            existe = (
                db.query(InstanciaVuelo)
                .filter(
                    InstanciaVuelo.fecha_salida >= inicio_dia,
                    InstanciaVuelo.fecha_salida <= fin_dia,
                )
                .first()
            )
            if not existe:
                # Vuelo 1: BOG -> MDE a las 8:00 AM
                fecha_v1 = datetime.combine(dia, time(8, 0))
                instancia_1 = InstanciaVuelo(
                    id_vuelo_programado="AV9301",
                    id_avion=avion.id_avion,
                    fecha_salida=fecha_v1,
                    asientos_disponibles_eco=25,
                    asientos_disponibles_biz=8,
                    estado="Programado",
                )
                # Vuelo 2: MDE -> CTG a las 10:30 AM (conexión para vuelos con escala BOG->CTG)
                fecha_v2 = datetime.combine(dia, time(10, 30))
                instancia_2 = InstanciaVuelo(
                    id_vuelo_programado="AV9303",
                    id_avion=avion.id_avion,
                    fecha_salida=fecha_v2,
                    asientos_disponibles_eco=25,
                    asientos_disponibles_biz=8,
                    estado="Programado",
                )
                # Vuelo 3: BOG -> CTG directo a las 14:00 PM
                # Para mañana (offset 1), le dejamos solo 2 asientos para prueba de concurrencia
                cupo_eco_v3 = 2 if offset == 1 else 20
                fecha_v3 = datetime.combine(dia, time(14, 0))
                instancia_3 = InstanciaVuelo(
                    id_vuelo_programado="AV9305",
                    id_avion=avion.id_avion,
                    fecha_salida=fecha_v3,
                    asientos_disponibles_eco=cupo_eco_v3,
                    asientos_disponibles_biz=4,
                    estado="Programado",
                )

                db.add_all([instancia_1, instancia_2, instancia_3])
                db.flush()

                # Precios para las 3 instancias
                for inst in [instancia_1, instancia_2, instancia_3]:
                    base = Decimal("150000.00") if inst.id_vuelo_programado == "AV9301" else Decimal("180000.00")
                    db.add_all([
                        PrecioVuelo(id_instancia_vuelo=inst.id_instancia_vuelo, id_tarifa=t_eco_promo.id_tarifa, precio_base=base),
                        PrecioVuelo(id_instancia_vuelo=inst.id_instancia_vuelo, id_tarifa=t_eco_flex.id_tarifa, precio_base=base + Decimal("70000.00")),
                        PrecioVuelo(id_instancia_vuelo=inst.id_instancia_vuelo, id_tarifa=t_biz_flex.id_tarifa, precio_base=base * Decimal("2.5")),
                    ])
                db.commit()

        # 7. Agencias Aliadas (B2B)
        if db.query(AgenciaAliada).count() == 0:
            print("Insertando agencias aliadas...")
            agencias = [
                AgenciaAliada(nombre_agencia="Despegar Colombia", codigo_api_key="APIKEY-DESPEGAR-2026-XYZ", porcentaje_comision=Decimal("5.00")),
                AgenciaAliada(nombre_agencia="Aviatur B2B", codigo_api_key="APIKEY-AVIATUR-2026-ABC", porcentaje_comision=Decimal("6.50")),
            ]
            db.add_all(agencias)
            db.commit()

        print("Población de datos iniciales completada exitosamente.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()

