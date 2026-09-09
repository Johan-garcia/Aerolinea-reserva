import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("OLAP_POSTGRES_SERVER", "localhost"),
    port=int(os.getenv("OLAP_POSTGRES_PORT", "5432")),
    user=os.getenv("OLAP_POSTGRES_USER", "postgres"),
    password=os.getenv("OLAP_POSTGRES_PASSWORD", "postgres"),
    dbname=os.getenv("OLAP_POSTGRES_DB", "aerolinea_olap"),
    connect_timeout=15,
)
cur = conn.cursor()

print("=" * 80)
print("CONSULTA 1: INGRESOS Y OCUPACIÓN POR RUTA")
print("=" * 80)
cur.execute("""
    SELECT 
        v.codigo_ruta,
        v.nombre_ruta,
        COUNT(f.id_fact_reserva) as total_boletos_vendidos,
        SUM(f.precio_boleto) as ingresos_totales,
        SUM(f.monto_neto_aerolinea) as ingresos_netos,
        SUM(f.es_cancelada) as total_cancelaciones
    FROM fact_reservas f
    JOIN dim_vuelo_ruta v ON f.id_dim_vuelo_ruta = v.id_dim_vuelo_ruta
    GROUP BY v.codigo_ruta, v.nombre_ruta
    ORDER BY ingresos_totales DESC;
""")
print(f"{'Ruta':10} | {'Nombre':25} | {'Boletos':8} | {'Ingresos Brutos':18} | {'Ingresos Netos':18} | {'Cancelaciones':14}")
print("-" * 105)
for r in cur.fetchall():
    print(f"{r[0]:10} | {r[1]:25} | {r[2]:8} | COP ${r[3]:>13,.2f} | COP ${r[4]:>13,.2f} | {r[5]:14}")

print("\n" + "=" * 80)
print("CONSULTA 2: INGRESOS Y PATRÓN DE CANCELACIÓN POR TARIFA")
print("=" * 80)
cur.execute("""
    SELECT 
        t.clase,
        t.tipo_regla,
        COUNT(f.id_fact_reserva) as reservas,
        SUM(f.precio_boleto) as ingresos,
        SUM(f.es_cancelada) as canceladas,
        ROUND(CAST(SUM(f.es_cancelada) AS NUMERIC) / COUNT(f.id_fact_reserva) * 100, 2) as tasa_cancelacion_pct
    FROM fact_reservas f
    JOIN dim_tarifa t ON f.id_dim_tarifa = t.id_dim_tarifa
    GROUP BY t.clase, t.tipo_regla
    ORDER BY ingresos DESC;
""")
print(f"{'Clase':12} | {'Tipo Regla':12} | {'Reservas':8} | {'Ingresos':18} | {'Canceladas':10} | {'Tasa Cancelación':16}")
print("-" * 85)
for r in cur.fetchall():
    print(f"{r[0]:12} | {r[1]:12} | {r[2]:8} | COP ${r[3]:>13,.2f} | {r[4]:10} | {r[5]}%")

print("\n" + "=" * 80)
print("CONSULTA 3: DESEMPEÑO POR CANAL DE VENTA (DIRECTO VS B2B)")
print("=" * 80)
cur.execute("""
    SELECT 
        a.canal_venta,
        a.nombre_agencia,
        COUNT(f.id_fact_reserva) as boletos_vendidos,
        SUM(f.precio_boleto) as volumen_ventas,
        SUM(f.monto_comision) as comisiones_pagadas,
        SUM(f.monto_neto_aerolinea) as neto_aerolinea
    FROM fact_reservas f
    JOIN dim_agencia a ON f.id_dim_agencia = a.id_dim_agencia
    GROUP BY a.canal_venta, a.nombre_agencia
    ORDER BY volumen_ventas DESC;
""")
print(f"{'Canal':14} | {'Agencia':26} | {'Boletos':8} | {'Ventas':18} | {'Comisiones':16} | {'Neto Aerolínea':18}")
print("-" * 110)
for r in cur.fetchall():
    print(f"{r[0]:14} | {r[1]:26} | {r[2]:8} | COP ${r[3]:>13,.2f} | COP ${r[4]:>11,.2f} | COP ${r[5]:>13,.2f}")

cur.close()
conn.close()
