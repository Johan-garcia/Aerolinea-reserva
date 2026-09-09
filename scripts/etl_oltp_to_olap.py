"""
============================================================================
PROYECTO: SISTEMA DE RESERVAS DE VUELOS - AEROLÍNEA REGIONAL
FASE 5.6: PIPELINE ETL (EXTRACT - TRANSFORM - LOAD)
ORIGEN: PostgreSQL RDS Transaccional (OLTP - aerolinea_db)
DESTINO: PostgreSQL RDS Analítico (OLAP - aerolinea_olap / Modelo en Estrella)
============================================================================
"""

import sys
import os
import time
from pathlib import Path
from datetime import datetime
from decimal import Decimal
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()


def get_db_connections():
    """Establece las conexiones hacia OLTP y OLAP en RDS."""
    oltp_conn = psycopg2.connect(
        host=os.getenv("POSTGRES_SERVER", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        dbname=os.getenv("POSTGRES_DB", "aerolinea_db"),
        connect_timeout=15,
    )

    olap_conn = psycopg2.connect(
        host=os.getenv("OLAP_POSTGRES_SERVER", "localhost"),
        port=int(os.getenv("OLAP_POSTGRES_PORT", "5432")),
        user=os.getenv("OLAP_POSTGRES_USER", "postgres"),
        password=os.getenv("OLAP_POSTGRES_PASSWORD", "postgres"),
        dbname=os.getenv("OLAP_POSTGRES_DB", "aerolinea_olap"),
        connect_timeout=15,
    )
    return oltp_conn, olap_conn


def run_etl():
    inicio = time.time()
    print("=" * 70)
    print("INICIANDO PROCESO ETL: OLTP (RDS) -> OLAP (RDS Star Schema)")
    print(f"Timestamp de inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    oltp_conn, olap_conn = get_db_connections()
    oltp_cur = oltp_conn.cursor()
    olap_cur = olap_conn.cursor()

    try:
        # ---------------------------------------------------------------------
        # 0. Limpieza previa de la BD Analítica para carga limpia/idempotente
        # ---------------------------------------------------------------------
        print("\n[Paso 0] Reiniciando tablas de destino en OLAP...")
        olap_cur.execute("""
            TRUNCATE TABLE fact_reservas, dim_pasajero, dim_vuelo_ruta, dim_tarifa CASCADE;
            DELETE FROM dim_agencia WHERE id_agencia_origen != -1;
        """)
        olap_conn.commit()

        # ---------------------------------------------------------------------
        # 1. Dimensión Pasajero (dim_pasajero)
        # ---------------------------------------------------------------------
        print("\n[Paso 1] Extrayendo y cargando 'dim_pasajero'...")
        oltp_cur.execute("""
            SELECT id_pasajero, tipo_documento, numero_documento, nombres, apellidos, email, telefono
            FROM pasajeros;
        """)
        pasajeros = oltp_cur.fetchall()

        dim_pasajero_rows = []
        for p in pasajeros:
            id_orig, t_doc, n_doc, nom, ape, email, tel = p
            nom_completo = f"{nom} {ape}".strip()
            dim_pasajero_rows.append((id_orig, t_doc, n_doc, nom, ape, nom_completo, email, tel))

        if dim_pasajero_rows:
            execute_values(
                olap_cur,
                """
                INSERT INTO dim_pasajero 
                (id_pasajero_origen, tipo_documento, numero_documento, nombres, apellidos, nombre_completo, email, telefono)
                VALUES %s;
                """,
                dim_pasajero_rows
            )
        olap_conn.commit()
        print(f"  -> {len(dim_pasajero_rows)} pasajeros cargados en dim_pasajero.")

        # Obtener mapa de id_pasajero_origen -> id_dim_pasajero
        olap_cur.execute("SELECT id_pasajero_origen, id_dim_pasajero FROM dim_pasajero;")
        map_pasajeros = dict(olap_cur.fetchall())

        # ---------------------------------------------------------------------
        # 2. Dimensión Vuelo y Ruta (dim_vuelo_ruta)
        # Desnormaliza: instancias_vuelo + vuelos_programados + rutas + aeropuertos + aviones
        # ---------------------------------------------------------------------
        print("\n[Paso 2] Desnormalizando y cargando 'dim_vuelo_ruta'...")
        oltp_cur.execute("""
            SELECT 
                iv.id_instancia_vuelo,
                vp.id_vuelo_programado,
                a_orig.id_aeropuerto,
                a_orig.nombre,
                a_orig.ciudad,
                a_orig.pais,
                a_dest.id_aeropuerto,
                a_dest.nombre,
                a_dest.ciudad,
                a_dest.pais,
                r.distancia_km,
                vp.hora_salida_programada,
                vp.hora_llegada_programada,
                iv.fecha_salida,
                av.modelo,
                av.capacidad_total,
                iv.estado
            FROM instancias_vuelo iv
            JOIN vuelos_programados vp ON iv.id_vuelo_programado = vp.id_vuelo_programado
            JOIN rutas r ON vp.id_ruta = r.id_ruta
            JOIN aeropuertos a_orig ON r.id_aeropuerto_origen = a_orig.id_aeropuerto
            JOIN aeropuertos a_dest ON r.id_aeropuerto_destino = a_dest.id_aeropuerto
            JOIN aviones av ON iv.id_avion = av.id_avion;
        """)
        vuelos = oltp_cur.fetchall()

        dim_vuelo_rows = []
        for v in vuelos:
            (
                id_instancia, cod_vuelo, orig_cod, orig_nom, orig_ciu, orig_pais,
                dest_cod, dest_nom, dest_ciu, dest_pais, dist, h_sal, h_lleg,
                fecha_salida_dt, avion_mod, avion_cap, estado_inst
            ) = v
            cod_ruta = f"{orig_cod}-{dest_cod}"
            nom_ruta = f"{orig_ciu} -> {dest_ciu}"
            fecha_salida_d = fecha_salida_dt.date() if hasattr(fecha_salida_dt, "date") else fecha_salida_dt

            dim_vuelo_rows.append((
                id_instancia, cod_vuelo, orig_cod, orig_nom, orig_ciu, orig_pais,
                dest_cod, dest_nom, dest_ciu, dest_pais, cod_ruta, nom_ruta, dist,
                h_sal, h_lleg, fecha_salida_dt, fecha_salida_d, avion_mod, avion_cap, estado_inst
            ))

        if dim_vuelo_rows:
            execute_values(
                olap_cur,
                """
                INSERT INTO dim_vuelo_ruta 
                (id_instancia_vuelo_origen, codigo_vuelo, id_aeropuerto_origen, aeropuerto_origen_nombre,
                 aeropuerto_origen_ciudad, aeropuerto_origen_pais, id_aeropuerto_destino, aeropuerto_destino_nombre,
                 aeropuerto_destino_ciudad, aeropuerto_destino_pais, codigo_ruta, nombre_ruta, distancia_km,
                 hora_salida_programada, hora_llegada_programada, fecha_hora_salida, fecha_salida,
                 avion_modelo, avion_capacidad_total, estado_instancia)
                VALUES %s;
                """,
                dim_vuelo_rows
            )
        olap_conn.commit()
        print(f"  -> {len(dim_vuelo_rows)} instancias desnormalizadas en dim_vuelo_ruta.")

        olap_cur.execute("SELECT id_instancia_vuelo_origen, id_dim_vuelo_ruta FROM dim_vuelo_ruta;")
        map_vuelos = dict(olap_cur.fetchall())

        # ---------------------------------------------------------------------
        # 3. Dimensión Tarifa (dim_tarifa)
        # ---------------------------------------------------------------------
        print("\n[Paso 3] Extrayendo y cargando 'dim_tarifa'...")
        oltp_cur.execute("""
            SELECT id_tarifa, clase, tipo_regla, porcentaje_reembolso
            FROM tarifas;
        """)
        tarifas = oltp_cur.fetchall()

        dim_tarifa_rows = []
        for t in tarifas:
            id_t, clase, tipo_r, reemb = t
            desc = f"{clase} - {tipo_r} ({reemb}% Reembolso)"
            dim_tarifa_rows.append((id_t, clase, tipo_r, reemb, desc))

        if dim_tarifa_rows:
            execute_values(
                olap_cur,
                """
                INSERT INTO dim_tarifa (id_tarifa_origen, clase, tipo_regla, porcentaje_reembolso, descripcion_tarifa)
                VALUES %s;
                """,
                dim_tarifa_rows
            )
        olap_conn.commit()
        print(f"  -> {len(dim_tarifa_rows)} tarifas cargadas en dim_tarifa.")

        olap_cur.execute("SELECT id_tarifa_origen, id_dim_tarifa FROM dim_tarifa;")
        map_tarifas = dict(olap_cur.fetchall())

        # ---------------------------------------------------------------------
        # 4. Dimensión Agencia (dim_agencia)
        # ---------------------------------------------------------------------
        print("\n[Paso 4] Extrayendo y cargando 'dim_agencia'...")
        oltp_cur.execute("""
            SELECT id_agencia, nombre_agencia, codigo_api_key, porcentaje_comision
            FROM agencias_aliadas;
        """)
        agencias = oltp_cur.fetchall()

        dim_agencia_rows = []
        for a in agencias:
            id_a, nom, key, com = a
            dim_agencia_rows.append((id_a, nom, key, com, "Agencia B2B"))

        if dim_agencia_rows:
            execute_values(
                olap_cur,
                """
                INSERT INTO dim_agencia (id_agencia_origen, nombre_agencia, codigo_api_key, porcentaje_comision, canal_venta)
                VALUES %s;
                """,
                dim_agencia_rows
            )
        olap_conn.commit()
        print(f"  -> {len(dim_agencia_rows)} agencias B2B cargadas en dim_agencia.")

        # Obtener mapa de agencias (incluyendo canal directo -1)
        olap_cur.execute("SELECT id_agencia_origen, id_dim_agencia FROM dim_agencia;")
        map_agencias = dict(olap_cur.fetchall())
        id_dim_agencia_directa = map_agencias.get(-1)

        # ---------------------------------------------------------------------
        # 5. Tabla de Hechos (fact_reservas)
        # Grano: 1 fila por trayecto vendido
        # ---------------------------------------------------------------------
        print("\n[Paso 5] Construyendo métricas y cargando 'fact_reservas'...")
        oltp_cur.execute("""
            SELECT 
                dr.id_detalle,
                r.id_reserva,
                r.codigo_pnr,
                dr.id_pasajero,
                dr.id_instancia_vuelo,
                dr.id_tarifa,
                r.id_agencia,
                r.fecha_creacion,
                r.estado,
                dr.estado_trayecto,
                p.metodo_pago,
                p.estado_pago,
                s.numero_asiento,
                dr.precio_aplicado,
                aa.porcentaje_comision,
                iv.fecha_salida
            FROM detalles_reserva dr
            JOIN reservas r ON dr.id_reserva = r.id_reserva
            JOIN instancias_vuelo iv ON dr.id_instancia_vuelo = iv.id_instancia_vuelo
            LEFT JOIN pagos p ON r.id_reserva = p.id_reserva
            LEFT JOIN asientos s ON dr.id_asiento = s.id_asiento
            LEFT JOIN agencias_aliadas aa ON r.id_agencia = aa.id_agencia;
        """)
        hechos_raw = oltp_cur.fetchall()

        fact_rows = []
        for row in hechos_raw:
            (
                id_det, id_res, pnr, id_pas, id_inst, id_tar, id_age,
                f_crea, est_res, est_tray, met_pago, est_pago, num_asiento,
                precio_ap, pct_comision, fecha_vuelo
            ) = row

            dim_pas_id = map_pasajeros.get(id_pas)
            dim_vue_id = map_vuelos.get(id_inst)
            dim_tar_id = map_tarifas.get(id_tar)
            dim_age_id = map_agencias.get(id_age, id_dim_agencia_directa)

            if not all([dim_pas_id, dim_vue_id, dim_tar_id, dim_age_id]):
                continue  # Evitar inconsistencias referenciales

            precio = Decimal(str(precio_ap))
            comision_pct = Decimal(str(pct_comision)) if pct_comision is not None else Decimal("0.00")
            monto_comision = (precio * comision_pct / Decimal("100.00")).quantize(Decimal("0.01"))
            monto_neto = precio - monto_comision

            es_confirmada = 1 if est_res == "Confirmada" else 0
            es_cancelada = 1 if est_res == "Cancelada" else 0

            # Cálculo de días de anticipación de compra
            dias_anticipacion = 0
            if fecha_vuelo and f_crea:
                d_vuelo = fecha_vuelo.date() if hasattr(fecha_vuelo, "date") else fecha_vuelo
                d_crea = f_crea.date() if hasattr(f_crea, "date") else f_crea
                dias_anticipacion = max((d_vuelo - d_crea).days, 0)

            f_crea_date = f_crea.date() if hasattr(f_crea, "date") else f_crea

            fact_rows.append((
                id_res, id_det, pnr,
                dim_pas_id, dim_vue_id, dim_tar_id, dim_age_id,
                f_crea, f_crea_date, est_res, est_tray,
                met_pago or "Sin Pago", est_pago or "Sin Pago", num_asiento,
                precio, monto_comision, monto_neto, 1,
                es_confirmada, es_cancelada, dias_anticipacion
            ))

        if fact_rows:
            execute_values(
                olap_cur,
                """
                INSERT INTO fact_reservas (
                    id_reserva_origen, id_detalle_origen, codigo_pnr,
                    id_dim_pasajero, id_dim_vuelo_ruta, id_dim_tarifa, id_dim_agencia,
                    fecha_reserva, fecha_reserva_date, estado_reserva, estado_trayecto,
                    metodo_pago, estado_pago, numero_asiento,
                    precio_boleto, monto_comision, monto_neto_aerolinea, cantidad_asientos,
                    es_confirmada, es_cancelada, dias_anticipacion_compra
                ) VALUES %s;
                """,
                fact_rows
            )
        olap_conn.commit()
        print(f"  -> {len(fact_rows)} registros de hechos cargados en fact_reservas.")

        # ---------------------------------------------------------------------
        # Resumen y Métricas Rápidas de Validación
        # ---------------------------------------------------------------------
        print("\n" + "=" * 70)
        print("RESUMEN DE CARGA EN BD ANALÍTICA (RDS OLAP):")
        print("=" * 70)
        olap_cur.execute("""
            SELECT 'dim_pasajero' as tabla, count(*) as registros FROM dim_pasajero
            UNION ALL
            SELECT 'dim_vuelo_ruta', count(*) FROM dim_vuelo_ruta
            UNION ALL
            SELECT 'dim_tarifa', count(*) FROM dim_tarifa
            UNION ALL
            SELECT 'dim_agencia', count(*) FROM dim_agencia
            UNION ALL
            SELECT 'fact_reservas', count(*) FROM fact_reservas;
        """)
        for tabla, regs in olap_cur.fetchall():
            print(f"  * {tabla:20}: {regs:6} registros")

        # Métricas de negocio
        olap_cur.execute("""
            SELECT 
                COUNT(*) as total_reservas,
                COALESCE(SUM(precio_boleto), 0) as ingresos_brutos,
                COALESCE(SUM(monto_neto_aerolinea), 0) as ingresos_netos,
                COALESCE(SUM(monto_comision), 0) as total_comisiones,
                COALESCE(SUM(es_cancelada), 0) as total_canceladas,
                ROUND(COALESCE(AVG(dias_anticipacion_compra), 0), 1) as prom_dias_anticipacion
            FROM fact_reservas;
        """)
        res = olap_cur.fetchone()
        print("\n" + "-" * 70)
        print("MÉTRICAS CLAVE GENERADAS EN EL DATA WAREHOUSE:")
        print(f"  - Total Reservas Facturadas : {res[0]}")
        print(f"  - Ingresos Brutos Totales    : COP ${res[1]:,.2f}")
        print(f"  - Ingresos Netos Aerolínea   : COP ${res[2]:,.2f}")
        print(f"  - Comisiones Pagadas Agencias: COP ${res[3]:,.2f}")
        print(f"  - Reservas Canceladas        : {res[4]}")
        print(f"  - Prom. Días de Anticipación : {res[5]} días")
        print("-" * 70)

        duracion = round(time.time() - inicio, 2)
        print(f"\n¡PROCESO ETL COMPLETADO CON ÉXITO EN {duracion} SEGUNDOS!")
        print("=" * 70)

    except Exception as e:
        olap_conn.rollback()
        print(f"\nERROR EN LA EJECUCIÓN DEL ETL: {e}")
        raise e
    finally:
        oltp_cur.close()
        oltp_conn.close()
        olap_cur.close()
        olap_conn.close()


if __name__ == "__main__":
    run_etl()
