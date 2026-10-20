# Sistema de Reservas de Vuelos y Panel Analítico: Aerolínea Regional

Proyecto de **Big Data e Ingeniería de Datos** (Juan Wilches, Johan García). Reúne los dos parciales en un
solo repositorio:

| Parcial | Qué aporta |
|---|---|
| **Parcial 1** | Backend transaccional (FastAPI + PostgreSQL) con búsqueda de vuelos directos y con escala, reservas multitrayecto, pagos, cancelación con auditoría, canal B2B para agencias, control de concurrencia sin sobreventa y un ETL OLTP → OLAP en modelo estrella |
| **Parcial 2** | Contrato de API verificable, **frontend** (clientes y panel gerencial), **job PySpark** (EMR) que limpia ~2 M reservas históricas, tablas en **Glue/Athena** y un endpoint de ocupación servido desde Athena; todo empaquetado en Docker |

Todo corre en local con Docker. Para AWS, el mismo `docker compose` se lanza en una EC2 cambiando una sola
variable (`ANALYTICS_ENGINE=athena`).

> Documentos relacionados:
> - [`GUIA_PARCIAL2.md`](GUIA_PARCIAL2.md): explicación detallada, decisiones de arquitectura (sección 5 del enunciado),
>   revisión de cumplimiento y preparación para la sustentación.
> - [`PARCIAL BIG DATA.md`](PARCIAL%20BIG%20DATA.md): documento del parcial 1 (requisitos RF/RNF, modelo ER, costos).
> - [`parcial2-harness/`](parcial2-harness/): suite de pruebas oficial del parcial 2 (no se modifica).

---

## Contenido

1. [Arquitectura](#1-arquitectura)
2. [Estructura del repositorio](#2-estructura-del-repositorio)
3. [Inicio rápido (local)](#3-inicio-rápido-local)
4. [Uso de la aplicación](#4-uso-de-la-aplicación)
5. [API](#5-api)
6. [Pipeline de datos (EMR / Spark)](#6-pipeline-de-datos-emr--spark)
7. [Pruebas](#7-pruebas)
8. [ETL del parcial 1 (OLTP → OLAP)](#8-etl-del-parcial-1-oltp--olap)
9. [Despliegue en AWS](#9-despliegue-en-aws)
10. [Configuración](#10-configuración)
11. [Costos](#11-costos)
12. [Solución de problemas](#12-solución-de-problemas)

---

## 1. Arquitectura

```
                     ┌─────────────────────── EC2 t3.small · docker compose ───────────────────────┐
 Navegador ─:3000─▶  │ frontend (nginx) ─/api/─▶ api (FastAPI, 2 workers) ─▶ db (PostgreSQL 16)     │
                     │  /  y  /manager              │                                              │
                     └──────────────────────────────┼──────────────────────────────────────────────┘
                                                    │ solo /analytics/*
                                                    ▼
 CSV crudos ─▶ S3 raw/ ─▶ EMR (PySpark: limpieza C1–C5) ─▶ S3 curated/ (Parquet por mes) ◀─ Glue Catalog ◀─ Athena

 En local:  S3 = carpeta data/   ·   EMR = contenedor apache/spark   ·   Athena = DuckDB dentro del api
```

Ideas clave:

- **Separación de cargas.** Las reservas usan PostgreSQL; la analítica nunca toca PostgreSQL (va a
  Athena/DuckDB sobre Parquet). Un panel lento no frena las reservas.
- **Sin sobreventa.** Un `UPDATE … WHERE seats_available > 0` atómico (parcial 2) y
  `SELECT … FOR UPDATE` con locks ordenados (parcial 1), más `CHECK (asientos >= 0)` en la base.
- **Mismo artefacto en todos lados.** El job PySpark y la imagen del backend son los mismos en local y
  en AWS; solo cambian rutas y variables de entorno.

---

## 2. Estructura del repositorio

```
.
├── app/                          # Backend FastAPI
│   ├── main.py                   # App: monta el contrato P2 en "/" y la API P1 en "/api/v1"
│   ├── api/
│   │   ├── contract.py           # P2: /health, /admin/flights, /flights/*, /reservations, /analytics/*
│   │   └── v1/endpoints/         # P1: flights, reservations (PNR, multitrayecto, B2B), health
│   ├── analytics/                # P2: motor analítico intercambiable
│   │   ├── base.py               #   SQL de negocio común (ocupación, top rutas, catálogo)
│   │   ├── athena_engine.py      #   Amazon Athena (AWS)
│   │   └── duckdb_engine.py      #   DuckDB sobre el Parquet local (desarrollo)
│   ├── crud/                     # Lógica transaccional (crud_contract.py = P2; el resto = P1)
│   ├── models/                   # ORM (contract.py = flights/reservations P2; el resto = modelo ER P1)
│   ├── schemas/                  # Pydantic (contract.py = P2)
│   └── core/                     # Configuración (variables de entorno) y conexión a la BD
├── frontend/                     # P2: HTML + CSS + JS sin build, servido por nginx (proxy /api/)
│   ├── public/index.html, app.js         # Página de clientes "/"
│   ├── public/manager.html, manager.js   # Panel gerencial "/manager"
│   └── nginx/default.conf.template
├── spark/jobs/curate_reservations.py     # P2: job PySpark (C1–C5, Parquet, métricas)
├── aws/
│   ├── emr/run_emr_job.sh        # Sube datos y job a S3 y lanza un cluster EMR que se apaga solo
│   └── athena/create_tables.sql  # DDL de las tablas en Glue/Athena (partition projection)
├── scripts/                      # Semillas, ETL P1, pruebas de concurrencia y de endpoints
├── tests/                        # Pruebas pytest del backend (P1 + motor Athena)
├── local_harness/                # Corre el harness oficial contra el sistema local
├── parcial2-harness/             # Harness oficial del parcial 2 (no editar harness/ ni tests/)
├── docker-compose.yml            # db + api + frontend, y pasos batch (datagen, spark-job)
├── docker-compose.aws.yml        # Override para la EC2 (Athena, BD sin puerto público)
├── cost_projection.yaml          # Proyección de costos mensual (R12)
├── Dockerfile                    # Imagen del backend
└── GUIA_PARCIAL2.md              # Guía detallada y decisiones
```

---

## 3. Inicio rápido (local)

**Requisitos:** Docker Desktop (o Docker Engine + Compose v2). Python 3.10+ solo para correr el harness.

```bash
# 1. Levantar base de datos, backend y frontend
docker compose up -d --build

# 2. Generar los datos crudos con la semilla del equipo (~2 M filas, menos de 1 minuto)
TEAM_SEED=12345 docker compose --profile batch run --rm datagen

# 3. "EMR local": limpiar los datos con PySpark y escribir el Parquet curado (~10 s)
docker compose --profile batch run --rm spark-job
```

Al arrancar, el backend crea las tablas, carga el catálogo del parcial 1 y crea **vuelos de demostración**
para los próximos 30 días (rutas BOG-MDE, MDE-BOG, BOG-CTG, CLO-CTG, BGA-BOG y BOG-SMR).

| URL | Qué es |
|---|---|
| http://localhost:3000/ | Página de clientes: elegir ruta, buscar, reservar |
| http://localhost:3000/manager | Panel gerencial: ocupación por ruta y mes |
| http://localhost:8000/docs | Swagger de toda la API (también en `/api/v1/docs`) |
| http://localhost:8000/health | Estado del servicio |

Apagar:

```bash
docker compose down        # conserva los datos de PostgreSQL
docker compose down -v     # borra también la base de datos
```

> Si cambia la semilla, repita los pasos 2 y 3. Use la misma semilla en
> `local_harness/config.local.yaml` y `parcial2-harness/config.yaml`.

---

## 4. Uso de la aplicación

### Página de clientes (`/`)

1. Elija una de las **rutas disponibles** (solo aparecen rutas con vuelos y sillas libres). También puede
   escribir los códigos IATA en el tablero grande o invertir la ruta.
2. Al elegir la ruta se buscan los vuelos de la fecha seleccionada (por defecto, mañana).
3. Pulse **Reservar** en un vuelo, escriba el nombre del pasajero, elija la clase y pulse **Confirmar reserva**.
4. Aparece un pasabordo con el **código de reserva**, que se puede consultar en `GET /reservations/{id}`.

### Panel gerencial (`/manager`)

1. Elija una de las **rutas del histórico**. Si no hay mes escrito, se usa el más reciente.
2. Puede escribir otro mes (`AAAA-MM`, entre 2023-01 y 2024-12) y pulsar **Ver ocupación**.
3. Se muestran la ocupación (p. ej. `81.2%`), sillas vendidas, capacidad, ingresos y cancelaciones, más
   una cabina de 100 asientos donde cada asiento azul es 1 %.
4. Abajo aparece el top 10 de rutas por ocupación; al hacer clic en una se carga su último mes.

---

## 5. API

### 5.1 Contrato del parcial 2 (raíz)

| Método y ruta | Cuerpo / parámetros | Respuesta |
|---|---|---|
| `GET /health` | – | `200` |
| `POST /admin/flights` | `{flight_id, route:"AAA-BBB", flight_date, capacity, price_cents}` | `201` (mismo cuerpo) · `409` si el id existe |
| `GET /flights/search` | `?origin=BOG&destination=MDE&date=YYYY-MM-DD` | `200` lista de `{flight_id, route, flight_date, seats_available, price_cents}` · `422` |
| `GET /flights/routes` | – | `200` rutas con vuelos disponibles (para el frontend) |
| `POST /reservations` | `{flight_id, passenger_name, fare_class:"ECONOMY"\|"BUSINESS"}` | `201 {reservation_id, flight_id, status:"CONFIRMED", passenger_name}` · `409` sin sillas · `404` vuelo inexistente |
| `GET /reservations/{id}` | – | `200` · `404` |
| `GET /analytics/occupancy` | `?route=AAA-BBB&month=YYYY-MM` | `200 {route, month, occupancy, seats_sold, seats_capacity, …}` · `404` sin datos |
| `GET /analytics/top-routes` | `?limit=10` | `200` rutas ordenadas por ocupación acumulada |
| `GET /analytics/catalog` | – | `200 {routes, months}` disponibles en el histórico |

Ejemplo:

```bash
curl -X POST localhost:8000/admin/flights -H 'content-type: application/json' \
  -d '{"flight_id":"AV100","route":"BOG-MDE","flight_date":"2030-01-15","capacity":2,"price_cents":15000}'
curl "localhost:8000/flights/search?origin=BOG&destination=MDE&date=2030-01-15"
curl -X POST localhost:8000/reservations -H 'content-type: application/json' \
  -d '{"flight_id":"AV100","passenger_name":"Ana Gómez","fare_class":"ECONOMY"}'
curl "localhost:8000/analytics/occupancy?route=BGA-BOG&month=2024-03"
```

### 5.2 API del parcial 1 (`/api/v1`)

| Método y ruta | Descripción | Requisito |
|---|---|---|
| `GET /api/v1/health` | Estado del servicio y de la BD | – |
| `GET /api/v1/flights/search?origen=&destino=&fecha_salida=&pasajeros=&clase=` | Itinerarios directos y con 1 escala | RF-01, RNF-01 |
| `GET /api/v1/flights/{id_instancia}` | Detalle e inventario de una instancia de vuelo | RF-01 |
| `POST /api/v1/reservations` | Reserva multitrayecto con pago atómico y bloqueo pesimista | RF-02, RF-04, RF-07, RNF-02 |
| `GET /api/v1/reservations/{pnr}?numero_documento=` | Consulta por PNR y documento | RF-05 |
| `POST /api/v1/reservations/{pnr}/cancel?numero_documento=` | Cancelación, devolución de cupo y auditoría | RF-05, RNF-05 |

**Canal B2B (RF-06):** incluya `codigo_api_key_agencia` en el cuerpo de la reserva. Agencias de prueba:
`APIKEY-DESPEGAR-2026-XYZ` (5 % de comisión) y `APIKEY-AVIATUR-2026-ABC` (6,5 %).

---

## 6. Pipeline de datos (EMR / Spark)

`spark/jobs/curate_reservations.py` procesa `flights.csv` y `reservations.csv` (generados por
`parcial2-harness/airline_data`) aplicando las reglas de limpieza del enunciado:

| Regla | Qué hace |
|---|---|
| C1 | `route`: quitar todo espacio en blanco y pasar a mayúsculas (` bog - mde ` → `BOG-MDE`) |
| C2 | `status`: quitar espacios en los extremos y pasar a mayúsculas |
| C3 | Conservar solo `CONFIRMED` y `CANCELLED` |
| C4 | Descartar `price_cents` vacío o ≤ 0 |
| C5 | Descartar `reservation_id` duplicados conservando la primera aparición |

Salida:

| Tabla | Formato | Columnas |
|---|---|---|
| `reservations_curated` | Parquet, partición `month=YYYY-MM` (24), un archivo por mes | `reservation_id, flight_id, route, fare_class, price_cents, status` + `month` |
| `route_month_metrics` | Parquet | `route, month, seats_capacity, seats_sold, occupancy, revenue_cents, bookings, cancellations` |

`occupancy = seats_sold / seats_capacity`, donde `seats_sold` cuenta solo CONFIRMED y `seats_capacity`
suma la capacidad de todos los vuelos de la ruta en el mes.

```bash
# Local (escribe en data/lake/curated/ y registra la corrida en data/lake/_emr_local/runs.jsonl)
docker compose --profile batch run --rm spark-job

# AWS (ver sección 9)
BUCKET=mi-bucket ./aws/emr/run_emr_job.sh
```

---

## 7. Pruebas

### 7.1 Harness oficial del parcial 2 contra el sistema local

```bash
python3 -m venv .venv
.venv/bin/pip install -r parcial2-harness/requirements.txt duckdb
.venv/bin/playwright install chromium

.venv/bin/python local_harness/run_local.py      # reporte en local_harness/report.md
```

`local_harness/run_local.py` usa la costura `harness/registry.py` del propio harness para inyectar la
configuración local y un adaptador que reemplaza a AWS (S3 = `data/lake`, Athena = DuckDB, historial de
EMR = el registro del job Spark). R10–R12 se verifican sobre el despliegue **planeado**
(`local_harness/simulated_deployment.yaml`). Resultado actual: **70 / 70**.

### 7.2 Pruebas del backend (parcial 1 + motor Athena)

```bash
docker compose run --rm --no-deps \
  -v "$PWD/tests:/workspace/tests" -v "$PWD/pytest.ini:/workspace/pytest.ini" \
  api pytest -q tests
```

15 pruebas: 11 de la API del parcial 1 (búsqueda, reservas de uno y varios trayectos, cancelación, B2B)
y 4 del motor Athena con un cliente simulado.

### 7.3 Scripts de evidencia del parcial 1

```bash
docker compose exec api python scripts/test_all_endpoints.py          # recorre todos los endpoints v1
docker compose exec api python scripts/test_concurrency.py            # 20 reservas simultáneas por 2 sillas
docker compose exec api python scripts/test_concurrency_evidence.py   # evidencia para el informe
```

---

## 8. ETL del parcial 1 (OLTP → OLAP)

Modelo estrella (`scripts/olap_star_schema.sql`): `fact_reservas` con las dimensiones `dim_pasajero`,
`dim_vuelo_ruta`, `dim_tarifa` y `dim_agencia`, en la base `aerolinea_olap` del mismo servidor PostgreSQL.

```bash
# Con el sistema arriba; cada script corre dentro de la imagen del backend
docker compose exec -e POSTGRES_SERVER=db -e OLAP_POSTGRES_SERVER=db api python scripts/setup_olap_database.py       # crea aerolinea_olap y el esquema estrella
docker compose exec -e POSTGRES_SERVER=db -e OLAP_POSTGRES_SERVER=db api python scripts/generate_sample_bookings.py  # 75 reservas de muestra en el OLTP
docker compose exec -e POSTGRES_SERVER=db -e OLAP_POSTGRES_SERVER=db api python scripts/etl_oltp_to_olap.py          # extrae, transforma y carga
docker compose exec -e POSTGRES_SERVER=db -e OLAP_POSTGRES_SERVER=db api python scripts/verify_olap_queries.py       # consultas de negocio
```

En el parcial 2 este camino se sustituyó por S3 + EMR + Athena para el histórico grande; se conserva
como antecedente.

---

## 9. Despliegue en AWS

Pensado para el **AWS Academy Learner Lab** (presupuesto de US$ 50). Orden recomendado:

**1. Bucket S3**

```bash
aws s3 mb s3://airline-<equipo>
```

**2. Job EMR (R4, R10)**: desde su equipo, con las credenciales del Lab y `data/raw` ya generado:

```bash
BUCKET=airline-<equipo> ./aws/emr/run_emr_job.sh
```

Sube los CSV y el job, crea un cluster con 1 master y 2 core **m4.large** (`--auto-terminate`,
`ActionOnFailure=TERMINATE_CLUSTER`), espera a que termine y muestra el estado de los pasos y las horas
normalizadas consumidas. Antes de la corrida completa, pruebe con una muestra:
`DATA_ROWS=50000 docker compose --profile batch run --rm datagen`.

**3. Glue Data Catalog + Athena (R5, R6)**: en la consola de Athena:

1. Configure la ubicación de resultados: `s3://airline-<equipo>/athena-results/`.
2. Ejecute `aws/athena/create_tables.sql` sentencia por sentencia, reemplazando `YOUR-BUCKET`.
   Las tablas usan *partition projection*, así que no hace falta crawler ni `MSCK REPAIR`.

**4. EC2 con la aplicación (R1–R3, R7–R9)**

- Instancia **t3.small**, Amazon Linux 2023, 20 GB gp3, perfil de instancia **`LabInstanceProfile`**
  (da acceso a Athena/S3 sin escribir credenciales).
- Security group: entrada en 3000 y 8000 desde cualquier lugar y 22 solo desde su IP.

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user && newgrp docker
# Plugin de Compose v2
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

git clone <url-del-repo> bigdata-service && cd bigdata-service
echo "ATHENA_OUTPUT=s3://airline-<equipo>/athena-results/" > .env
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
curl localhost:8000/health        # {"status":"ok","analytics_engine":"athena"}
```

**5. Harness real**

```bash
cd parcial2-harness
# Edite config.yaml: semilla, http://<IP-PUBLICA>:8000 y :3000, y el bucket de resultados
pytest            # escribe report.md y report.json
```

**6. Control de costos**

- Detenga la EC2 al terminar el día; el Lab cambia la IP pública al reiniciar, así que actualice `config.yaml`.
- Compruebe que no quede ningún cluster EMR activo: `aws emr list-clusters --active`.

---

## 10. Configuración

Variables de entorno del backend (ver `app/core/config.py` y `.env.example`):

| Variable | Por defecto | Uso |
|---|---|---|
| `DATABASE_URL` | lo arma `docker-compose.yml` | Conexión a PostgreSQL (se fuerza el driver psycopg2) |
| `UVICORN_WORKERS` | `2` | Procesos del servidor |
| `ANALYTICS_ENGINE` | `duckdb` | `duckdb` (local) o `athena` (AWS) |
| `LAKE_PATH` | `/data/lake` | Raíz del Parquet local (solo DuckDB) |
| `ATHENA_DATABASE` | `airline_analytics` | Base de datos de Glue |
| `ATHENA_WORKGROUP` | `primary` | Workgroup de Athena |
| `ATHENA_OUTPUT` | – | `s3://…/athena-results/`; obligatorio en AWS |
| `AWS_REGION` | `us-east-1` | Región |
| `ANALYTICS_TIMEOUT_SECONDS` | `9` | Límite por consulta (R7 exige ≤ 10 s) |
| `ANALYTICS_CACHE_TTL_SECONDS` | `0` | Caché en memoria del endpoint analítico (desactivada) |
| `DEMO_ROUTES` | `BOG-MDE,…` | Rutas de los vuelos de demostración |
| `DEMO_DAYS` | `30` | Días hacia adelante con vuelos de demostración |
| `DEV_RELOAD` | `0` | `1` = uvicorn con `--reload` (desarrollo) |

Variables de los pasos batch: `TEAM_SEED` (semilla), `DATA_ROWS` (filas, por defecto 2.000.000) y
`SPARK_DRIVER_MEMORY` (por defecto `3g`).

---

## 11. Costos

`cost_projection.yaml` (el harness suma los `line_items`):

| Servicio | Detalle | USD/mes |
|---|---|---|
| EC2 | t3.small 24/7 (PostgreSQL + FastAPI + nginx) | 15,20 |
| EBS | 20 GB gp3 | 1,60 |
| S3 | ~0,2 GB + peticiones | 0,10 |
| Athena | ~9.000 consultas × 10 MB mínimo | 0,45 |
| EMR | 1 corrida/mes, 3 × m4.large, 1 h | 0,40 |
| Glue | Data Catalog en capa gratuita | 0,00 |
| **Total** | | **≈ 17,75** |

El análisis de escenarios (datos ×10, consultas ×10) está en `GUIA_PARCIAL2.md`, sección 6.

---

## 12. Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `/analytics/*` responde 503 "No hay datos curados" | Falta correr el job: `docker compose --profile batch run --rm spark-job` |
| `ModuleNotFoundError: psycopg` | URL de BD sin driver; ya se corrige en `config.py`. Reconstruya: `docker compose up -d --build api` |
| El buscador no muestra rutas | No hay vuelos futuros: reinicie el api (recrea los vuelos demo) o cree vuelos con `POST /admin/flights` |
| El job Spark falla por memoria | Baje `SPARK_DRIVER_MEMORY=2g` o aumente la memoria de Docker Desktop |
| Puerto 5432 ocupado | Otro PostgreSQL local: `POSTGRES_PORT=5433 docker compose up -d` |
| En AWS, Athena da `AccessDenied` | La EC2 no tiene `LabInstanceProfile` o falta `ATHENA_OUTPUT` en `.env` |
| R4 falla en AWS ("not written during an EMR run") | El Parquet debe escribirlo EMR: no suba `data/lake` a S3 a mano |
