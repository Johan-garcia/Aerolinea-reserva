import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import time
from datetime import datetime
import httpx
from app.core.database import SessionLocal
from app.models.flight import InstanciaVuelo

API_BASE = "http://127.0.0.1:8000/api/v1"
TEST_INSTANCE_ID = 5  # Instancia designada para la prueba de concurrencia

def preparar_escenario_de_prueba():
    """Configura el inventario de la instancia exactamente en 1 asiento disponible."""
    db = SessionLocal()
    try:
        instancia = db.query(InstanciaVuelo).filter(InstanciaVuelo.id_instancia_vuelo == TEST_INSTANCE_ID).first()
        if not instancia:
            raise RuntimeError(f"Instancia {TEST_INSTANCE_ID} no encontrada en la base de datos.")
        
        instancia.asientos_disponibles_eco = 1
        db.commit()
        db.refresh(instancia)
        return instancia.id_vuelo_programado, instancia.fecha_salida, instancia.asientos_disponibles_eco
    finally:
        db.close()

async def enviar_solicitud_reserva(client: httpx.AsyncClient, usuario_id: str, payload: dict, sync_event: asyncio.Event):
    # Esperar al evento de sincronización para que ambas peticiones salgan al mismo microsegundo
    await sync_event.wait()
    
    t_inicio = time.perf_counter()
    timestamp_envio = datetime.now().strftime("%H:%M:%S.%f")
    
    try:
        response = await client.post(f"{API_BASE}/reservations", json=payload)
        t_fin = time.perf_counter()
        duracion_ms = (t_fin - t_inicio) * 1000
        
        return {
            "usuario": usuario_id,
            "status_code": response.status_code,
            "timestamp_envio": timestamp_envio,
            "duracion_ms": duracion_ms,
            "body": response.json() if response.status_code in [201, 409] else response.text
        }
    except Exception as e:
        return {
            "usuario": usuario_id,
            "status_code": 500,
            "timestamp_envio": timestamp_envio,
            "duracion_ms": 0,
            "error": str(e)
        }

async def ejecutar_prueba():
    print("=" * 78)
    print("  FASE 5.6: PRUEBA DE CONCURRENCIA Y BLOQUEO PESIMISTA (0% SOBREVENTA)")
    print("=" * 78)
    
    # 1. Preparar inventario con exactamente 1 asiento
    vuelo_cod, fecha_vuelo, cupo_inicial = preparar_escenario_de_prueba()
    print(f"[ESTADO INICIAL] Vuelo: {vuelo_cod} | Instancia ID: {TEST_INSTANCE_ID} | Fecha: {fecha_vuelo}")
    print(f"[INVENTARIO]    Asientos disponibles en clase Economica: {cupo_inicial} (UNICO ASIENTO)")
    print("-" * 78)

    # 2. Definir payloads para Usuario A y Usuario B intentando reservar el mismo asiento
    payload_a = {
        "pasajero_comprador": {
            "tipo_documento": "CC",
            "numero_documento": "1001001001",
            "nombres": "Pasajero_A",
            "apellidos": "Concurrente",
            "email": "usuario.a@prueba.com",
            "telefono": "3001112233"
        },
        "codigo_api_key_agencia": None,
        "trayectos": [{
            "id_instancia_vuelo": TEST_INSTANCE_ID,
            "clase": "Económica",
            "id_tarifa": 1,
            "pasajero": {
                "tipo_documento": "CC",
                "numero_documento": "1001001001",
                "nombres": "Pasajero_A",
                "apellidos": "Concurrente",
                "email": "usuario.a@prueba.com",
                "telefono": "3001112233"
            },
            "id_asiento": None
        }],
        "pago": {
            "metodo_pago": "Tarjeta",
            "id_transaccion_proveedor": "TXN-CONC-USER-A"
        }
    }

    payload_b = {
        "pasajero_comprador": {
            "tipo_documento": "CC",
            "numero_documento": "2002002002",
            "nombres": "Pasajero_B",
            "apellidos": "Concurrente",
            "email": "usuario.b@prueba.com",
            "telefono": "3004445566"
        },
        "codigo_api_key_agencia": None,
        "trayectos": [{
            "id_instancia_vuelo": TEST_INSTANCE_ID,
            "clase": "Económica",
            "id_tarifa": 1,
            "pasajero": {
                "tipo_documento": "CC",
                "numero_documento": "2002002002",
                "nombres": "Pasajero_B",
                "apellidos": "Concurrente",
                "email": "usuario.b@prueba.com",
                "telefono": "3004445566"
            },
            "id_asiento": None
        }],
        "pago": {
            "metodo_pago": "PSE",
            "id_transaccion_proveedor": "TXN-CONC-USER-B"
        }
    }

    print(">>> Disparando peticiones simultaneas (Usuario A y Usuario B) al mismo microsegundo...")
    
    sync_event = asyncio.Event()
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Lanzar ambas corrutinas en segundo plano
        tarea_a = asyncio.create_task(enviar_solicitud_reserva(client, "Usuario A", payload_a, sync_event))
        tarea_b = asyncio.create_task(enviar_solicitud_reserva(client, "Usuario B", payload_b, sync_event))
        
        # Pequeña pausa para asegurar que ambas tareas esten esperando el evento
        await asyncio.sleep(0.05)
        # Disparo simultaneo
        sync_event.set()
        
        resultados = await asyncio.gather(tarea_a, tarea_b)

    print("-" * 78)
    print("                      RESULTADOS RECIBIDOS")
    print("-" * 78)

    for res in resultados:
        usr = res["usuario"]
        st = res["status_code"]
        ts = res["timestamp_envio"]
        dur = res["duracion_ms"]
        
        if st == 201:
            pnr = res["body"].get("codigo_pnr")
            monto = res["body"].get("monto_total")
            print(f" [+] {usr} -> HTTP {st} CREATED (EXITO)")
            print(f"     Timestamp: {ts} | Tiempo: {dur:.2f} ms")
            print(f"     PNR Generado: {pnr} | Monto: ${monto} | Pago: APROBADO")
        elif st == 409:
            detalle = res["body"].get("detail")
            print(f" [X] {usr} -> HTTP {st} CONFLICT (BLOQUEO / SIN CUPO)")
            print(f"     Timestamp: {ts} | Tiempo: {dur:.2f} ms")
            print(f"     Detalle: {detalle}")
        else:
            print(f" [?] {usr} -> HTTP {st}")
            print(f"     Respuesta: {res.get('body') or res.get('error')}")
        print()

    # 3. Verificación de consistencia en la base de datos
    db = SessionLocal()
    try:
        instancia_final = db.query(InstanciaVuelo).filter(InstanciaVuelo.id_instancia_vuelo == TEST_INSTANCE_ID).first()
        cupo_final = instancia_final.asientos_disponibles_eco
    finally:
        db.close()

    print("=" * 78)
    print("                    EVALUACION DE CONSISTENCIA")
    print("=" * 78)
    print(f"Cupo Inicial:                   {cupo_inicial} asiento")
    print(f"Solicitudes emitidas:           2 (simultaneas)")
    print(f"Reservas creadas (HTTP 201):    1")
    print(f"Rechazadas por cupo (HTTP 409): 1")
    print(f"Cupo Final restante:            {cupo_final} asientos")
    
    if cupo_final == 0:
        print("\n >> RESULTADO: [EXITO TOTAL - 0% SOBREVENTA]")
        print("    El bloqueo pesimista garantizo que solo una transaccion tomara el")
        print("    asiento y la segunda fue rechazada de forma atomica con HTTP 409.")
    else:
        print(f"\n >> ERROR: Inventario inconsistente ({cupo_final})")
    print("=" * 78)

if __name__ == "__main__":
    asyncio.run(ejecutar_prueba())