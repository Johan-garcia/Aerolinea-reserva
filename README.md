# Sistema de Reservas de Vuelos - Aerolínea Regional (Backend OLTP)

Sistema transaccional de alta concurrencia desarrollado en **FastAPI** y **SQLAlchemy 2.0**, con motor de base de datos **PostgreSQL**, diseñado para cumplir con los requerimientos funcionales y no funcionales del Examen Parcial de Big Data.

---

## 1. Arquitectura del Proyecto

El backend está estructurado siguiendo los principios de **arquitectura modular en capas**, facilitando la separación de responsabilidades, la mantenibilidad y la escalabilidad horizontal:

```
/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── flights.py         # Búsqueda y disponibilidad de vuelos (RF-01)
│   │       │   ├── reservations.py    # Creación, consulta y cancelación de reservas (RF-02, RF-04, RF-05)
│   │       │   └── health.py          # Chequeo de salud del servicio y base de datos
│   │       └── router.py              # Router centralizado v1
│   ├── core/
│   │   ├── config.py                  # Variables de entorno y configuración con Pydantic Settings
│   │   └── database.py                # Engine SQLAlchemy y sesión con pooling para OLTP
│   ├── crud/
│   │   ├── crud_flight.py             # Consultas optimizadas para vuelos directos y con escala
│   │   └── crud_reservation.py        # Transacciones con bloqueo pesimista y auditoría inmutable
│   ├── models/                        # Entidades ORM (Mapeo fiel de diagrama ER)
│   │   ├── airport.py                 # Aeropuerto (IATA, ciudad, país)
│   │   ├── route.py                   # Ruta (origen, destino, distancia)
│   │   ├── airplane.py                # Avión (modelo, capacidad, filas, columnas)
│   │   ├── flight.py                  # VueloProgramado e InstanciaVuelo
│   │   ├── fare.py                    # Tarifa y PrecioVuelo
│   │   ├── seat.py                    # Asiento físico y auditoría
│   │   ├── passenger.py               # Pasajero (identificación, datos de contacto)
│   │   ├── agency.py                  # AgenciaAliada (B2B con API Key y comisiones)
│   │   ├── reservation.py             # Reserva (PNR) y DetalleReserva (itinerario multitrayecto)
│   │   ├── payment.py                 # Pago (pasarela simulada y transacción atómica)
│   │   └── audit.py                   # AuditoriaReserva (Historial inmutable UTC - RNF-05)
│   ├── schemas/                       # Validación estricta con Pydantic v2
│   │   ├── common.py                  # Enums (estados, clases, métodos de pago)
│   │   ├── flight.py                  # DTOs de búsqueda e itinerarios
│   │   ├── reservation.py             # DTOs para creación, consulta y respuesta de reserva
│   │   ├── passenger.py               # DTOs para registro de pasajeros
│   │   └── payment.py                 # DTOs para procesamiento de pago
│   └── main.py                        # Punto de entrada de la aplicación FastAPI
├── scripts/
│   ├── seed_data.py                   # Población inicial del catálogo (rutas, vuelos, tarifas, agencias)
│   └── test_concurrency.py            # Prueba automatizada de concurrencia y sobreventa (0% oversell)
├── requirements.txt                   # Dependencias de Python
├── Dockerfile                         # Contenedor optimizado de producción
├── docker-compose.yml                 # Orquestación de PostgreSQL 16 y FastAPI
└── README.md
```

---

## 2. Control de Concurrencia y Prevención de Sobreventa (RNF-02)

Para garantizar consistencia estricta (**ACID**) y **0% sobreventa** en temporadas de alta demanda:

1. **Bloqueo Pesimista a Nivel de Fila (`SELECT ... FOR UPDATE`):**
   Al procesar una solicitud de reserva en `app/crud/crud_reservation.py`, el sistema bloquea inmediatamente la fila de la `InstanciaVuelo` correspondiente:
   ```python
   instancia = (
       db.query(InstanciaVuelo)
       .filter(InstanciaVuelo.id_instancia_vuelo == i_id)
       .with_for_update()
       .first()
   )
   ```
2. **Validación Atómica de Inventario:**
   Si la clase solicitada (`Económica` o `Ejecutiva`) no cuenta con asientos disponibles (`asientos_disponibles < 1`), la transacción lanza una excepción `HTTP 409 Conflict` provocando un rollback inmediato.
3. **Ordenamiento de Locks para Evitar Deadlocks:**
   En reservas con múltiples trayectos (conexiones/escalas), los IDs de las instancias se ordenan numéricamente antes de solicitar los bloqueos, eliminando la posibilidad de interbloqueos cíclicos.
4. **Restricción a Nivel de Motor (PostgreSQL Safety Net):**
   La tabla `instancias_vuelo` cuenta con restricciones `CheckConstraint` explícitas:
   ```sql
   CONSTRAINT chk_asientos_eco_no_negativo CHECK (asientos_disponibles_eco >= 0)
   CONSTRAINT chk_asientos_biz_no_negativo CHECK (asientos_disponibles_biz >= 0)
   ```
   Cualquier decremento por debajo de cero es abortado automáticamente por PostgreSQL.

---

## 3. Puesta en Marcha Rápida

### Opción A: Usando Docker Compose (Recomendado)
```bash
# 1. Clonar el repositorio y levantar los contenedores
docker-compose up --build -d

# 2. Poblar datos iniciales
docker-compose exec api python scripts/seed_data.py

# 3. Ejecutar prueba de concurrencia
docker-compose exec api python scripts/test_concurrency.py
```

### Opción B: Entorno Local
```bash
# 1. Crear entorno virtual e instalar dependencias
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configurar variables de entorno
cp .env.example .env

# 3. Iniciar el servidor FastAPI
uvicorn app.main:app --reload --port 8000
```

---

## 4. Documentación Interactiva de la API

Una vez iniciado el servidor, accede a:
- **Swagger UI:** [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- **ReDoc:** [http://localhost:8000/api/v1/redoc](http://localhost:8000/api/v1/redoc)
- **Health Check:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

## 5. Endpoints Principales

| Método | Ruta | Descripción | Requisito |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/flights/search` | Búsqueda de disponibilidad (directos y hasta 1 escala) | **RF-01, RNF-01** |
| `GET` | `/api/v1/flights/{id}` | Detalle de instancia de vuelo e inventario | **RF-01** |
| `POST` | `/api/v1/reservations` | Creación atómica de reserva multitrayecto con bloqueo pesimista | **RF-02, RF-04, RNF-02** |
| `GET` | `/api/v1/reservations/{pnr}?numero_documento=...` | Consulta de reserva por PNR y documento | **RF-05** |
| `POST` | `/api/v1/reservations/{pnr}/cancel?numero_documento=...` | Cancelación de reserva, liberación de cupo y auditoría | **RF-05, RNF-05** |

