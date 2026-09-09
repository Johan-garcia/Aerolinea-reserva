import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import random
import uuid
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models import (
    Pasajero,
    Reserva,
    DetalleReserva,
    Pago,
    InstanciaVuelo,
    PrecioVuelo,
    Tarifa,
    AgenciaAliada,
    Asiento,
)

NOMBRES = [
    ("Carlos", "Gómez"), ("María", "Rodríguez"), ("Andrés", "López"),
    ("Laura", "Martínez"), ("Juan", "Wilches"), ("Johan", "García"),
    ("Daniela", "Pérez"), ("Felipe", "Hernández"), ("Valentina", "Torres"),
    ("Santiago", "Ramírez"), ("Camila", "Castro"), ("Alejandro", "Morales"),
    ("Paola", "Vargas"), ("David", "Ortiz"), ("Natalia", "Rojas"),
    ("Mateo", "Silva"), ("Carolina", "Mendoza"), ("Gabriel", "Guerrero")
]

METODOS_PAGO = ["Tarjeta de Crédito", "PSE", "Transferencia Bancaria"]


def generar_pnr(db: Session) -> str:
    chars = string.ascii_uppercase + "23456789"
    while True:
        pnr = "".join(random.choices(chars, k=6))
        if not db.query(Reserva).filter(Reserva.codigo_pnr == pnr).first():
            return pnr


def seed_sample_bookings(num_reservas: int = 70):
    db: Session = SessionLocal()
    try:
        print(f"Generando {num_reservas} reservas de muestra en OLTP...")
        instancias = db.query(InstanciaVuelo).all()
        if not instancias:
            print("No hay instancias de vuelo en la base de datos.")
            return

        agencias = db.query(AgenciaAliada).all()
        tarifas = db.query(Tarifa).all()
        asientos = db.query(Asiento).all()

        reservas_creadas = 0

        for i in range(num_reservas):
            # 1. Seleccionar Pasajero
            nombre, apellido = random.choice(NOMBRES)
            doc_num = f"{random.randint(10000000, 1099999999)}"
            email = f"{nombre.lower()}.{apellido.lower()}{random.randint(10, 99)}@gmail.com"
            telefono = f"3{random.randint(100000000, 299999999)}"

            pasajero = db.query(Pasajero).filter(Pasajero.numero_documento == doc_num).first()
            if not pasajero:
                pasajero = Pasajero(
                    tipo_documento="CC",
                    numero_documento=doc_num,
                    nombres=nombre,
                    apellidos=apellido,
                    email=email,
                    telefono=telefono,
                )
                db.add(pasajero)
                db.flush()

            # 2. Canal de Venta (70% Directo Web, 30% Agencia B2B)
            es_agencia = random.random() < 0.30
            agencia_id = random.choice(agencias).id_agencia if es_agencia and agencias else None

            # 3. Seleccionar Instancia de Vuelo
            instancia = random.choice(instancias)

            # 4. Seleccionar Tarifa
            tarifa = random.choice(tarifas)

            # Obtener precio base
            precio_obj = (
                db.query(PrecioVuelo)
                .filter(
                    PrecioVuelo.id_instancia_vuelo == instancia.id_instancia_vuelo,
                    PrecioVuelo.id_tarifa == tarifa.id_tarifa,
                )
                .first()
            )
            precio = precio_obj.precio_base if precio_obj else Decimal("180000.00")

            # 5. Fecha de Reserva (entre 1 y 25 días antes de la salida del vuelo)
            dias_antes = random.randint(1, 25)
            fecha_vuelo = instancia.fecha_salida
            fecha_reserva = fecha_vuelo - timedelta(days=dias_antes, hours=random.randint(1, 12))
            if fecha_reserva > datetime.now(timezone.utc):
                fecha_reserva = datetime.now(timezone.utc) - timedelta(days=random.randint(0, 5))

            # 6. Estado de la Reserva (85% Confirmada, 15% Cancelada)
            es_cancelada = random.random() < 0.15
            estado_reserva = "Cancelada" if es_cancelada else "Confirmada"
            estado_trayecto = "Cancelado" if es_cancelada else "Confirmado"

            # 7. Asignar Asiento compatible si aplica
            asiento_sel = None
            asientos_clase = [a for a in asientos if a.clase == tarifa.clase]
            if asientos_clase and random.random() < 0.80:
                asiento_sel = random.choice(asientos_clase).id_asiento

            # Crear Reserva
            pnr = generar_pnr(db)
            reserva = Reserva(
                codigo_pnr=pnr,
                id_pasajero_comprador=pasajero.id_pasajero,
                id_agencia=agencia_id,
                fecha_creacion=fecha_reserva,
                estado=estado_reserva,
                monto_total=precio,
            )
            db.add(reserva)
            db.flush()

            # Crear Detalle
            detalle = DetalleReserva(
                id_reserva=reserva.id_reserva,
                id_instancia_vuelo=instancia.id_instancia_vuelo,
                id_pasajero=pasajero.id_pasajero,
                id_asiento=asiento_sel,
                id_tarifa=tarifa.id_tarifa,
                precio_aplicado=precio,
                estado_trayecto=estado_trayecto,
            )
            db.add(detalle)
            db.flush()

            # Crear Pago
            pago = Pago(
                id_reserva=reserva.id_reserva,
                fecha_pago=fecha_reserva + timedelta(minutes=random.randint(2, 15)),
                monto=precio,
                metodo_pago=random.choice(METODOS_PAGO),
                id_transaccion_proveedor=str(uuid.uuid4()),
                estado_pago="Aprobado",
            )
            db.add(pago)

            # Actualizar inventario si confirmada
            if not es_cancelada:
                if tarifa.clase == "Económica" and instancia.asientos_disponibles_eco > 0:
                    instancia.asientos_disponibles_eco -= 1
                elif tarifa.clase == "Ejecutiva" and instancia.asientos_disponibles_biz > 0:
                    instancia.asientos_disponibles_biz -= 1

            reservas_creadas += 1

        db.commit()
        print(f"Se crearon exitosamente {reservas_creadas} reservas con sus pasajeros, detalles y pagos.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_sample_bookings(75)
