import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models.flight import InstanciaVuelo
from app.models.reservation import Reserva
from app.models.audit import AuditoriaReserva

client = TestClient(app)
HOY = date.today().isoformat()
MANANA = (date.today() + timedelta(days=1)).isoformat()


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "docs" in data
    assert "health" in data


def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_search_direct_flights():
    response = client.get(
        "/api/v1/flights/search",
        params={"origen": "BOG", "destino": "MDE", "fecha_salida": HOY, "pasajeros": 1}
    )
    assert response.status_code == 200
    itinerarios = response.json()
    assert len(itinerarios) > 0

    itinerario = itinerarios[0]
    assert itinerario["tipo"] == "Directo"
    assert itinerario["escalas_count"] == 0
    assert len(itinerario["trayectos"]) == 1
    trayecto = itinerario["trayectos"][0]
    assert trayecto["id_aeropuerto_origen"] == "BOG"
    assert trayecto["id_aeropuerto_destino"] == "MDE"
    assert len(trayecto["tarifas"]) >= 3


def test_search_flights_with_layover():
    response = client.get(
        "/api/v1/flights/search",
        params={"origen": "BOG", "destino": "CTG", "fecha_salida": HOY, "pasajeros": 1}
    )
    assert response.status_code == 200
    itinerarios = response.json()
    assert len(itinerarios) >= 2

    tipos = [i["tipo"] for i in itinerarios]
    assert "Directo" in tipos
    assert "Con Escala" in tipos

    escala = next(i for i in itinerarios if i["tipo"] == "Con Escala")
    assert escala["escalas_count"] == 1
    assert len(escala["trayectos"]) == 2
    assert escala["trayectos"][0]["id_aeropuerto_origen"] == "BOG"
    assert escala["trayectos"][0]["id_aeropuerto_destino"] == "MDE"
    assert escala["trayectos"][1]["id_aeropuerto_origen"] == "MDE"
    assert escala["trayectos"][1]["id_aeropuerto_destino"] == "CTG"


def test_get_flight_detail():
    response = client.get("/api/v1/flights/1")
    assert response.status_code == 200
    data = response.json()
    assert data["id_instancia_vuelo"] == 1
    assert data["id_vuelo_programado"] == "AV9301"
    assert data["asientos_disponibles_eco"] > 0
    assert len(data["tarifas"]) > 0


def test_get_flight_detail_not_found():
    response = client.get("/api/v1/flights/999999")
    assert response.status_code == 404
    assert "no encontrada" in response.json()["detail"].lower()


def test_create_reservation_single_leg():
    db = SessionLocal()
    instancia_antes = db.query(InstanciaVuelo).filter(InstanciaVuelo.id_instancia_vuelo == 1).first()
    cupo_eco_antes = instancia_antes.asientos_disponibles_eco
    db.close()

    payload = {
        "pasajero_comprador": {
            "tipo_documento": "CC",
            "numero_documento": "1098765432",
            "nombres": "Carlos",
            "apellidos": "Gomez",
            "email": "carlos.gomez@test.com",
            "telefono": "3109876543"
        },
        "trayectos": [
            {
                "id_instancia_vuelo": 1,
                "clase": "Económica",
                "id_tarifa": 1,
                "pasajero": {
                    "tipo_documento": "CC",
                    "numero_documento": "1098765432",
                    "nombres": "Carlos",
                    "apellidos": "Gomez",
                    "email": "carlos.gomez@test.com",
                    "telefono": "3109876543"
                },
                "id_asiento": None
            }
        ],
        "pago": {
            "metodo_pago": "Tarjeta",
            "id_transaccion_proveedor": "TXN-TEST-001"
        }
    }

    response = client.post("/api/v1/reservations", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert "codigo_pnr" in data
    assert len(data["codigo_pnr"]) == 6
    assert data["estado"] == "Confirmada"
    assert float(data["monto_total"]) == 150000.0
    assert len(data["detalles"]) == 1
    assert len(data["pagos"]) == 1
    assert data["pagos"][0]["estado_pago"] == "Aprobado"

    db = SessionLocal()
    instancia_despues = db.query(InstanciaVuelo).filter(InstanciaVuelo.id_instancia_vuelo == 1).first()
    assert instancia_despues.asientos_disponibles_eco == cupo_eco_antes - 1
    db.close()


def test_create_reservation_multi_leg():
    # Reserva de 2 tramos (escala BOG -> MDE -> CTG)
    payload = {
        "pasajero_comprador": {
            "tipo_documento": "CC",
            "numero_documento": "5544332211",
            "nombres": "Mariana",
            "apellidos": "Rios",
            "email": "mariana.rios@test.com",
            "telefono": "3156789012"
        },
        "trayectos": [
            {
                "id_instancia_vuelo": 1,
                "clase": "Económica",
                "id_tarifa": 1,
                "pasajero": {
                    "tipo_documento": "CC",
                    "numero_documento": "5544332211",
                    "nombres": "Mariana",
                    "apellidos": "Rios",
                    "email": "mariana.rios@test.com",
                    "telefono": "3156789012"
                },
                "id_asiento": None
            },
            {
                "id_instancia_vuelo": 2,
                "clase": "Económica",
                "id_tarifa": 1,
                "pasajero": {
                    "tipo_documento": "CC",
                    "numero_documento": "5544332211",
                    "nombres": "Mariana",
                    "apellidos": "Rios",
                    "email": "mariana.rios@test.com",
                    "telefono": "3156789012"
                },
                "id_asiento": None
            }
        ],
        "pago": {
            "metodo_pago": "Tarjeta",
            "id_transaccion_proveedor": "TXN-MULTI-001"
        }
    }

    response = client.post("/api/v1/reservations", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert len(data["detalles"]) == 2
    assert float(data["monto_total"]) == 330000.0  # 150000 + 180000


def test_create_and_cancel_reservation_with_inventory_restoration():
    doc = "9876543210"
    payload = {
        "pasajero_comprador": {
            "tipo_documento": "CC",
            "numero_documento": doc,
            "nombres": "Laura",
            "apellidos": "Martinez",
            "email": "laura.m@test.com",
            "telefono": "3123456789"
        },
        "trayectos": [
            {
                "id_instancia_vuelo": 2,
                "clase": "Económica",
                "id_tarifa": 1,
                "pasajero": {
                    "tipo_documento": "CC",
                    "numero_documento": doc,
                    "nombres": "Laura",
                    "apellidos": "Martinez",
                    "email": "laura.m@test.com",
                    "telefono": "3123456789"
                },
                "id_asiento": None
            }
        ],
        "pago": {
            "metodo_pago": "PSE",
            "id_transaccion_proveedor": "TXN-CANCEL-001"
        }
    }

    db = SessionLocal()
    instancia_antes = db.query(InstanciaVuelo).filter(InstanciaVuelo.id_instancia_vuelo == 2).first()
    cupo_eco_inicial = instancia_antes.asientos_disponibles_eco
    db.close()

    # 1. Crear reserva
    resp_create = client.post("/api/v1/reservations", json=payload)
    assert resp_create.status_code == 201
    pnr = resp_create.json()["codigo_pnr"]

    db = SessionLocal()
    instancia_intermedia = db.query(InstanciaVuelo).filter(InstanciaVuelo.id_instancia_vuelo == 2).first()
    assert instancia_intermedia.asientos_disponibles_eco == cupo_eco_inicial - 1
    db.close()

    # 2. Consultar reserva
    resp_get = client.get(f"/api/v1/reservations/{pnr}", params={"numero_documento": doc})
    assert resp_get.status_code == 200
    assert resp_get.json()["codigo_pnr"] == pnr
    assert resp_get.json()["estado"] == "Confirmada"

    # 3. Intentar consultar con documento incorrecto
    resp_wrong_doc = client.get(f"/api/v1/reservations/{pnr}", params={"numero_documento": "0000000000"})
    assert resp_wrong_doc.status_code == 404

    # 4. Cancelar reserva
    resp_cancel = client.post(f"/api/v1/reservations/{pnr}/cancel", params={"numero_documento": doc})
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["estado"] == "Cancelada"

    # 5. Intentar cancelar nuevamente (debe retornar 400 Bad Request)
    resp_re_cancel = client.post(f"/api/v1/reservations/{pnr}/cancel", params={"numero_documento": doc})
    assert resp_re_cancel.status_code == 400

    # 6. Verificar liberacion de inventario
    db = SessionLocal()
    instancia_final = db.query(InstanciaVuelo).filter(InstanciaVuelo.id_instancia_vuelo == 2).first()
    assert instancia_final.asientos_disponibles_eco == cupo_eco_inicial

    # 7. Verificar log inmutable de auditoria
    auditorias = db.query(AuditoriaReserva).filter(AuditoriaReserva.id_reserva == resp_cancel.json()["id_reserva"]).all()
    acciones = [a.accion for a in auditorias]
    assert "CREACION" in acciones
    assert "CANCELACION" in acciones
    db.close()


def test_b2b_agency_reservation_valid():
    payload = {
        "codigo_api_key_agencia": "APIKEY-DESPEGAR-2026-XYZ",
        "pasajero_comprador": {
            "tipo_documento": "CC",
            "numero_documento": "7000123456",
            "nombres": "Cliente",
            "apellidos": "Despegar",
            "email": "despegar.cliente@test.com",
            "telefono": "3009998877"
        },
        "trayectos": [
            {
                "id_instancia_vuelo": 1,
                "clase": "Económica",
                "id_tarifa": 2,
                "pasajero": {
                    "tipo_documento": "CC",
                    "numero_documento": "7000123456",
                    "nombres": "Cliente",
                    "apellidos": "Despegar",
                    "email": "despegar.cliente@test.com",
                    "telefono": "3009998877"
                },
                "id_asiento": None
            }
        ],
        "pago": {
            "metodo_pago": "Transferencia",
            "id_transaccion_proveedor": "B2B-TXN-001"
        }
    }

    response = client.post("/api/v1/reservations", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["nombre_agencia"] == "Despegar Colombia"


def test_b2b_agency_reservation_invalid_key():
    payload = {
        "codigo_api_key_agencia": "APIKEY-INVALIDA-INEXISTENTE",
        "pasajero_comprador": {
            "tipo_documento": "CC",
            "numero_documento": "7000123456",
            "nombres": "Cliente",
            "apellidos": "Invalido",
            "email": "cliente.invalido@test.com",
            "telefono": "3009998877"
        },
        "trayectos": [
            {
                "id_instancia_vuelo": 1,
                "clase": "Económica",
                "id_tarifa": 1,
                "pasajero": {
                    "tipo_documento": "CC",
                    "numero_documento": "7000123456",
                    "nombres": "Cliente",
                    "apellidos": "Invalido",
                    "email": "cliente.invalido@test.com",
                    "telefono": "3009998877"
                },
                "id_asiento": None
            }
        ],
        "pago": {
            "metodo_pago": "Tarjeta",
            "id_transaccion_proveedor": "TXN-ERR"
        }
    }

    response = client.post("/api/v1/reservations", json=payload)
    assert response.status_code == 401
    assert "no válida" in response.json()["detail"].lower()