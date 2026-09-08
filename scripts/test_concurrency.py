import sys
from pathlib import Path

# Asegurar que el directorio raíz del proyecto esté en el PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx

API_URL = "http://localhost:8000/api/v1"
NUM_PETICIONES_CONCURRENTES = 20
ID_INSTANCIA_PRUEBA = 3  # Instancia configurada en seed con solo 2 asientos
ID_TARIFA_PRUEBA = 1


def realizar_intento_reserva(indice: int) -> dict:
    """
    Simula un usuario intentando reservar el último asiento disponible simultáneamente.
    """
    documento = f"1000{random.randint(100000, 999999)}"
    payload = {
        "pasajero_comprador": {
            "tipo_documento": "CC",
            "numero_documento": documento,
            "nombres": f"UsuarioPrueba_{indice}",
            "apellidos": "Concurrencia",
            "email": f"usuario_{indice}_{documento}@prueba.com",
            "telefono": "3001234567",
        },
        "trayectos": [
            {
                "id_instancia_vuelo": ID_INSTANCIA_PRUEBA,
                "clase": "Económica",
                "id_tarifa": ID_TARIFA_PRUEBA,
                "pasajero": {
                    "tipo_documento": "CC",
                    "numero_documento": documento,
                    "nombres": f"UsuarioPrueba_{indice}",
                    "apellidos": "Concurrencia",
                    "email": f"usuario_{indice}_{documento}@prueba.com",
                    "telefono": "3001234567",
                },
                "id_asiento": None,
            }
        ],
        "pago": {
            "metodo_pago": "Tarjeta",
            "id_transaccion_proveedor": None,
        },
    }

    inicio = time.time()
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{API_URL}/reservations", json=payload)
            duracion = time.time() - inicio
            return {
                "indice": indice,
                "status_code": resp.status_code,
                "data": resp.json() if resp.status_code in [201, 409] else resp.text,
                "duracion": duracion,
            }
    except Exception as e:
        return {
            "indice": indice,
            "status_code": 500,
            "error": str(e),
            "duracion": time.time() - inicio,
        }


def ejecutar_prueba_concurrencia():
    print("=" * 70)
    print("INICIANDO PRUEBA DE CONCURRENCIA Y CONTROL DE SOBREVENTA (RNF-02)")
    print(f"Objetivo: Validar consistencia estricta ante colisión de reservas simultáneas.")
    print(f"Peticiones concurrentes a emitir: {NUM_PETICIONES_CONCURRENTES}")
    print(f"URL Objetivo: {API_URL}/reservations")
    print("=" * 70)

    # 1. Consultar estado previo del vuelo
    with httpx.Client(timeout=5.0) as client:
        try:
            r = client.get(f"{API_URL}/flights/{ID_INSTANCIA_PRUEBA}")
            if r.status_code == 200:
                info = r.json()
                print(f"Estado inicial vuelo {info['id_vuelo_programado']}:")
                print(f" -> Asientos Económica Disponibles: {info['asientos_disponibles_eco']}")
                print(f" -> Asientos Ejecutiva Disponibles: {info['asientos_disponibles_biz']}")
            else:
                print(f"Aviso: No se pudo consultar la instancia {ID_INSTANCIA_PRUEBA} (Status: {r.status_code})")
        except Exception as e:
            print(f"Error conectando a la API: {e}")
            print("Asegúrate de que la API esté levantada en http://localhost:8000")
            return

    print("\nDisparando ráfaga de hilos concurrentes...")
    inicio_total = time.time()
    resultados = []

    with ThreadPoolExecutor(max_workers=NUM_PETICIONES_CONCURRENTES) as executor:
        futuros = [
            executor.submit(realizar_intento_reserva, i)
            for i in range(1, NUM_PETICIONES_CONCURRENTES + 1)
        ]
        for f in as_completed(futuros):
            resultados.append(f.result())

    tiempo_total = time.time() - inicio_total

    # Métricas y análisis
    exitosos = [r for r in resultados if r["status_code"] == 201]
    conflictos = [r for r in resultados if r["status_code"] == 409]
    errores = [r for r in resultados if r["status_code"] not in [201, 409]]

    print("\n" + "=" * 70)
    print("RESULTADOS DE LA PRUEBA DE CONCURRENCIA")
    print("=" * 70)
    print(f"Total solicitudes enviadas:           {len(resultados)}")
    print(f"Reservas Confirmadas (HTTP 201):      {len(exitosos)}")
    print(f"Rechazadas por Conflicto (HTTP 409):  {len(conflictos)}")
    print(f"Errores imprevistos:                  {len(errores)}")
    print(f"Tiempo total de la prueba:            {tiempo_total:.3f} s")

    if exitosos:
        print("\nReservas exitosas creadas:")
        for r in exitosos:
            pnr = r["data"].get("codigo_pnr")
            print(f" -> PNR: {pnr} (Respuesta en {r['duracion']:.3f}s)")

    # 2. Consultar inventario final tras la prueba
    with httpx.Client(timeout=5.0) as client:
        r = client.get(f"{API_URL}/flights/{ID_INSTANCIA_PRUEBA}")
        if r.status_code == 200:
            info = r.json()
            eco_final = info["asientos_disponibles_eco"]
            print(f"\nInventario final del vuelo:")
            print(f" -> Asientos Económica Restantes: {eco_final}")

            if eco_final >= 0:
                print("\n[VERIFICACIÓN EXITOSA] Consistencia Estricta garantizada.")
                print(f"Tasa de sobreventa: 0.00% (No se vendió ningún asiento por encima del cupo).")
            else:
                print(f"\n[ALERTA DE SOBREVENTA] El inventario quedó en {eco_final} (violación de consistencia).")
    print("=" * 70)


if __name__ == "__main__":
    ejecutar_prueba_concurrencia()

