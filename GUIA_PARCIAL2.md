# Guía del Parcial 2: Panel analítico de la aerolínea

Este documento explica **qué se construyó, cómo funciona y cómo ejecutarlo paso a paso**, primero en
local (todo con Docker) y después en AWS. También deja un borrador de las decisiones que pide la
sección 5 del enunciado, para que el equipo lo revise y lo defienda en la sustentación.

> Estado actual: el sistema corre completo en local y el harness oficial (sin modificar) da
> **70 / 70** contra él. R4–R7 y R10–R12 se verificaron con un adaptador local que reemplaza a
> AWS (ver sección 4). La nota real la da la corrida en AWS.

---

## 1. Qué pide el parcial (en una frase por bloque)

| Bloque | Qué hay que entregar | Requisitos |
|---|---|---|
| Backend transaccional | API del contrato: crear vuelos, buscar, reservar sin sobreventa, consultar reserva | R1, R2, R3 |
| Batch (EMR) | Job PySpark que limpia ~2 M filas sucias (reglas C1–C5) y escribe Parquet particionado por mes | R4 |
| Catálogo y consultas | Tablas `reservations_curated` y `route_month_metrics` en Glue, consultadas con Athena | R5, R6 |
| Endpoint analítico | `GET /analytics/occupancy` que lee de Athena en < 10 s | R7 |
| Frontend | Página de cliente (buscar → reservar → confirmación) y panel gerencial `/manager` | R8, R9 |
| Costo y simplicidad | Nada de EMR encendido, instancias pequeñas, ≤ 8 servicios, `cost_projection.yaml` | R10, R11, R12 |

---

## 2. Qué se hizo

### 2.1 Arquitectura

```
                         ┌──────────────────────── EC2 t3.small (docker compose) ────────────────────────┐
  Navegador ──:3000──▶   │  frontend (nginx)  ──/api/──▶  api (FastAPI, 2 workers)  ──▶  db (PostgreSQL)  │
                         │   /  y  /manager                │                                               │
                         └─────────────────────────────────┼───────────────────────────────────────────────┘
                                                           │ solo /analytics/*
                                                           ▼
   data/raw (CSV) ──▶ S3 raw/ ──▶ EMR (PySpark, C1–C5) ──▶ S3 curated/ (Parquet) ◀── Glue Catalog ◀── Athena

   En local:  S3 = carpeta data/  ·  EMR = contenedor apache/spark  ·  Athena = DuckDB dentro del api
```

La **misma imagen** del backend sirve en ambos entornos; solo cambia la variable `ANALYTICS_ENGINE`
(`duckdb` en local, `athena` en AWS). El job PySpark es el **mismo archivo** en local y en EMR; solo
cambian las rutas (`/data/...` o `s3://...`).

### 2.2 Archivos nuevos o modificados

| Ruta | Qué es |
|---|---|
| `app/models/contract.py` | Tablas `flights` y `reservations` del contrato (la API del Parcial 1 sigue en `/api/v1`) |
| `app/crud/crud_contract.py` | Reserva atómica sin sobreventa (UPDATE condicional, ver 2.3) |
| `app/api/contract.py` | Endpoints del contrato en la raíz: `/health`, `/admin/flights`, `/flights/search`, `/reservations`, `/analytics/*`, y `/flights/routes` (extra, para el selector de rutas) |
| `app/analytics/` | Motor analítico intercambiable: `athena_engine.py` (AWS) y `duckdb_engine.py` (local), misma SQL |
| `app/core/config.py` | Variables nuevas (`ANALYTICS_ENGINE`, `ATHENA_*`, …) y corrección del driver de PostgreSQL |
| `scripts/seed_demo_flights.py` | Crea vuelos de demostración para los próximos 30 días (para probar el frontend a mano) |
| `scripts/entrypoint.sh` | Arranque de producción: uvicorn con 2 workers, sin `--reload` |
| `spark/jobs/curate_reservations.py` | **El job PySpark** (C1–C5, Parquet particionado, métricas) |
| `frontend/` | Frontend estático (HTML + CSS + JS, sin build) servido por nginx, que además hace de proxy `/api/` |
| `docker-compose.yml` | db + api + frontend, y los pasos batch `datagen` y `spark-job` (perfil `batch`) |
| `docker-compose.aws.yml` | Override para el EC2: Athena en vez de DuckDB, PostgreSQL sin puerto público |
| `aws/emr/run_emr_job.sh` | Sube datos y job a S3 y lanza un cluster EMR que se apaga solo |
| `aws/athena/create_tables.sql` | DDL de las dos tablas en Glue/Athena (con partition projection) |
| `cost_projection.yaml` | Proyección de costos mensual (R12) |
| `local_harness/` | Runner que ejecuta el harness oficial contra el sistema local |

### 2.3 Cómo se evita la sobreventa (R2)

Una sola sentencia hace la verificación y el descuento a la vez:

```sql
UPDATE flights SET seats_available = seats_available - 1
WHERE flight_id = :id AND seats_available > 0
RETURNING price_cents;
```

PostgreSQL bloquea la fila durante el UPDATE. Las transacciones concurrentes esperan y, al obtener el
bloqueo, **vuelven a evaluar** `seats_available > 0` contra el valor ya confirmado. Si el UPDATE no
devuelve fila: o el vuelo no existe (404) o no quedan sillas (409). Nunca hay 5xx. Además la tabla
tiene `CHECK (seats_available >= 0)` como red de seguridad. Evidencia del harness: en 5 rondas de
50 peticiones simultáneas, exactamente 1 respuesta 201 y 49 respuestas 409; con K = 5 (el K de nuestra semilla), exactamente 5.

Es más simple y rápido que el `SELECT … FOR UPDATE` del Parcial 1 porque el bloqueo dura solo un
UPDATE y un INSERT.

### 2.4 El job PySpark (R4)

`spark/jobs/curate_reservations.py`, en orden:

1. Lee los CSV con todas las columnas como texto (así un precio vacío o raro no rompe la lectura).
2. **C1** `route`: `upper(regexp_replace(route, '\s+', ''))` sobre los vuelos.
3. **C2** `status`: quita espacios en los extremos y pasa a mayúsculas.
4. **C3** conserva solo `CONFIRMED` y `CANCELLED`.
5. **C4** descarta `price_cents` nulo o ≤ 0 y lo convierte a `bigint`.
6. **C5** quita `reservation_id` duplicados conservando **la primera aparición**: numera las filas en
   orden de lectura (`monotonically_increasing_id`) y se queda con `row_number() = 1` por id.
7. Une con vuelos para obtener `route` y `month` (`YYYY-MM` de `flight_date`).
8. Escribe `reservations_curated` con `repartition("month").partitionBy("month")`: **un archivo por mes**,
   24 particiones.
9. Calcula `route_month_metrics`: capacidad = suma de capacidad de **todos** los vuelos de la ruta en
   el mes; vendidas/ingresos/bookings = solo CONFIRMED; cancelaciones = CANCELLED;
   ocupación = vendidas / capacidad.

Verificado contra el oráculo del harness (semilla 24306, 12 rutas): 1.977.131 filas curadas (exacto), ingresos
por mes exactos, y capacidad, vendidas, ingresos y cancelaciones idénticos en las 288 filas de métricas (12 rutas × 24 meses)
(diferencia de ocupación = 0,0).

> **Ojo con `bookings`:** el contrato (`DATA.md` y el enunciado) dice que `bookings` cuenta solo
> CONFIRMED, pero el oráculo del harness cuenta todas las reservas. Seguimos el contrato. El harness no
> valida esa columna, pero conviene mencionarlo en el documento.

### 2.5 Frontend (R8, R9)

- **`/` (clientes):** arriba aparece una opción por cada ruta con vuelos disponibles
  (`GET /flights/routes`); al elegirla se llenan origen y destino y se busca de inmediato. La ruta se ve en grande, como en un tablero de aeropuerto (`BOG ✈ MDE`),
  con la ciudad debajo. Se elige la fecha, se busca y cada vuelo aparece como un talón de pasabordo.
  Al pulsar *Reservar* se abre debajo el formulario (nombre y clase) y al confirmar se muestra un
  pasabordo con el **código de reserva** (`data-testid="confirmation-id"`, texto exacto del id).
- **`/manager` (gerencia):** una opción por cada ruta del histórico (sale de Athena); al elegirla se
  consulta con el mes escrito o, si no hay, con el más reciente. Resultado: la ocupación en grande (`78.4%`, `data-testid="occupancy-value"`),
  sillas vendidas, capacidad, ingresos y cancelaciones, y una **cabina de 100 asientos** donde cada
  asiento azul es 1 % de ocupación. Abajo, el top 10 de rutas por ocupación (clic en una ruta carga
  su último mes). Los campos autocompletan con las rutas y meses que existen.
- Todos los `data-testid` del Apéndice A.3 están presentes. Los campos de texto de ruta se conservan
  porque el harness los llena con `fill()`, que solo funciona sobre inputs; las opciones los llenan por el usuario. Diseño adaptable a móvil, foco visible con
  teclado y respeto de `prefers-reduced-motion`.
- El navegador solo habla con nginx; nginx reenvía `/api/*` al backend. Por eso no hay problemas de
  CORS y la misma imagen funciona en local y en EC2.

---

## 3. Cómo ejecutarlo en local, paso a paso

Requisitos: Docker Desktop encendido. Python 3 solo hace falta para correr el harness.

```bash
# 1. Levantar BD + backend + frontend
docker compose up -d --build

# 2. Generar los datos crudos con la semilla del equipo (≈ 2 M filas, < 1 min)
#    Cambie TEAM_SEED por la semilla asignada (y la misma en local_harness/config.local.yaml).
TEAM_SEED=24306 docker compose --profile batch run --rm datagen

# 3. "EMR local": ejecutar el job PySpark (≈ 10 s en un portátil)
docker compose --profile batch run --rm spark-job
```

Listo. Abra:

| URL | Qué es |
|---|---|
| http://localhost:3000/ | Página de clientes (hay vuelos demo BOG→MDE y otros para los próximos 30 días) |
| http://localhost:3000/manager | Panel gerencial (pruebe una ruta del top 10 y un mes entre 2023-01 y 2024-12) |
| http://localhost:8000/docs | Swagger del backend |

### Correr el harness contra el sistema local

```bash
python3 -m venv .venv
.venv/bin/pip install -r parcial2-harness/requirements.txt duckdb
.venv/bin/playwright install chromium

.venv/bin/python local_harness/run_local.py      # escribe local_harness/report.md
```

Comandos útiles:

```bash
docker compose logs -f api                 # ver logs del backend
docker compose down                        # apagar (los datos de PostgreSQL se conservan)
docker compose down -v                     # apagar y borrar la BD
```

---

## 4. Cómo funciona el harness en local (y qué es aproximado)

El harness trae una "costura" de pruebas (`harness/registry.py`) para inyectar una configuración y un
adaptador AWS distinto. `local_harness/run_local.py` la usa **sin modificar nada del harness**:

| En AWS el harness mira… | En local se usa… |
|---|---|
| Historial de pasos EMR COMPLETED | `data/lake/_emr_local/runs.jsonl`, que escribe el job Spark al terminar |
| Archivos Parquet en S3 | `data/lake/curated/` |
| Tablas en Glue | El esquema real de los Parquet (columnas, tipos, partición `month`) |
| Consultas Athena | DuckDB sobre los mismos Parquet |
| Historial de consultas de Athena | `data/lake/_athena_local/query_log.jsonl`, que escribe el backend en cada consulta |
| RDS/EC2/EMR facturables | El despliegue **planeado** de `local_harness/simulated_deployment.yaml` |

Aproximaciones que hay que tener presentes:

- Los **bytes escaneados de R6** se estiman como el tamaño de la partición que toca la consulta. En
  Athena es un valor real; con un archivo Parquet por mes debería quedar por debajo del límite igual.
- **R10–R12** en local validan el plan, no recursos reales. Hay que repetir la corrida en AWS.

---

## 5. Despliegue en AWS

La guía paso a paso, con scripts para cada etapa, está en **[DESPLIEGUE_AWS.md](DESPLIEGUE_AWS.md)**:
bucket S3 → EC2 t3.small (`aws/ec2/bootstrap.sh`) → datos → EMR (`aws/emr/run_emr_job.sh`) →
Glue/Athena (`aws/athena/setup_athena.sh`) → harness (`aws/harness/run_harness.sh`) → apagado
(`aws/estado_aws.sh`).

---

## 6. Borrador de decisiones (sección 5 del enunciado)

> Es un punto de partida: revísenlo y ajústenlo con sus palabras, porque en la sustentación deben
> poder defender cada frase.

**Modelo de alojamiento.** Backend, frontend y PostgreSQL corren en contenedores dentro de **una sola
EC2 t3.small**. Es la opción más barata que cumple R1 (p95 medido de 0,03 s frente al límite de 1 s)
y R2 (la garantía de no sobreventa la da PostgreSQL, no el tamaño de la máquina). RDS db.t3.micro
añadiría unos US$ 14/mes y otro servicio facturable; a cambio daría backups y parches gestionados.
Para un panel académico con presupuesto de US$ 50 se prioriza *Cost Optimization*; si fuera
producción, RDS sería la primera mejora por *Reliability*. Contenedores: *Operational Excellence*
(el mismo artefacto en local y en AWS).

**Por qué EMR.** El job limpia y deduplica 2 M filas con reglas que requieren lógica fila a fila y una
ventana (C5 "conservar la primera aparición"), une dos fuentes y escribe Parquet particionado. Athena
sola cobraría por escanear el CSV crudo en cada consulta del panel y sus CTAS tienen límites de
particiones por consulta y menos control sobre el orden. Un Glue job también serviría, pero el curso
exige EMR. Elegimos **EMR en cluster** (1 master + 2 core m4.large, el único tipo permitido) con
`--auto-terminate` y `ActionOnFailure=TERMINATE_CLUSTER`: el cluster muere solo al terminar o fallar
(R10). Cada corrida usa unas 12 horas-instancia normalizadas, lejos del tope de 150.
*Cost Optimization*, *Sustainability*.

**Distribución de los datos.** Parquet es columnar y comprimido: el CSV de 81 MB queda en ~19 MB y
una consulta que solo lee `route` y `status` no lee el resto de columnas. Particionar por `month`
hace que una consulta de un mes lea una sola de 24 particiones (~0,8 MB en vez de ~19 MB). Sin
partición, R6 fallaría porque Athena escanearía el dataset completo en cada consulta mensual.
*Performance Efficiency*, *Cost Optimization*.

**Cómo obtiene el panel sus números.** El endpoint consulta Athena sobre `route_month_metrics`, una
tabla de 288 filas (~20 KB) precalculada por el job. Latencia: 1–3 s típicos de Athena, dentro de los
10 s de R7. Costo: cada consulta factura el mínimo de 10 MB (≈ US$ 0,00005). Frescura: la que dé la
última corrida del job (mensual). **No usamos caché por defecto**: el ahorro sería de centavos y
añade riesgo de servir datos viejos; queda disponible con `ANALYTICS_CACHE_TTL_SECONDS` si el volumen
de consultas creciera 1000×. *Cost Optimization*, *Performance Efficiency*.

**Separación de cargas.** Las consultas analíticas nunca tocan PostgreSQL: van a Athena, que corre en
la infraestructura de AWS y lee de S3. El job batch corre en EMR, fuera del EC2. Así, el panel y el
batch no compiten por CPU ni conexiones con las reservas (R1, R2). *Reliability*,
*Performance Efficiency*.

**Tabla de justificación de servicios**

| Servicio | Alternativa considerada | Requisito | Pilar(es) |
|---|---|---|---|
| EC2 t3.small + Docker | RDS + EC2, ECS/Fargate, Elastic Beanstalk | R1, R2, R11, R12 | Cost Optimization, Operational Excellence |
| PostgreSQL (en contenedor) | RDS db.t3.micro | R2 (consistencia ACID) | Reliability, Cost Optimization |
| S3 | EBS / HDFS en EMR | R4, R6 | Cost Optimization, Sustainability |
| EMR (cluster efímero m4.large) | Glue job, Athena CTAS, EMR Serverless | R4, R10 | Cost Optimization, Performance Efficiency |
| Glue Data Catalog (DDL + partition projection) | Glue Crawler | R5 | Operational Excellence |
| Athena | Redshift, RDS analítica (Parcial 1) | R6, R7 | Cost Optimization, Performance Efficiency |

Total: 6 servicios facturables (EC2, EBS, S3, EMR, Glue, Athena), dentro del máximo de 8 (R11).

**Proyección de costos.** Ver `cost_projection.yaml`: **≈ US$ 17,75/mes**, dominado por la EC2 encendida
24/7 (86 %). Con datos ×10 (20 M filas): EMR pasa de ~US$ 0,40 a ~US$ 1–2 por corrida (más nodos o más
tiempo), S3 y el escaneo por partición crecen linealmente pero siguen en centavos, y el endpoint no
cambia porque `route_month_metrics` sigue siendo pequeña (rutas × meses). Con consultas ×10 (90.000/mes):
Athena sube a ~US$ 4,5 por el mínimo de 10 MB; ahí sí convendría activar la caché. Con tráfico de
reservas ×10 habría que pasar a t3.medium o separar PostgreSQL en RDS (~US$ 30–45/mes). Lo que más
reduce costo y huella (*Sustainability*) es apagar la EC2 fuera del horario de uso.

---

## 7. Preparación para la sustentación

El profesor puede pedir un cambio en vivo. Qué tocar en cada caso:

| Cambio pedido | Dónde | Qué más se ve afectado |
|---|---|---|
| Otra regla de limpieza (p. ej. descartar `price_cents` > X) | `clean_reservations()` en el job | Volver a correr el job; cambian el conteo de filas (R4) y las métricas (R6, R7, R9). El oráculo del harness no la conoce, así que R4 fallaría a propósito |
| Otra agregación (p. ej. ingreso por clase de tarifa) | `build_metrics()` + DDL de la tabla + `QueryEngine` en `app/analytics/base.py` + endpoint | Glue (nueva columna), endpoint y panel |
| Ocupación contando también canceladas | `build_metrics()` (`seats_sold`) | R6, R7, R9 dejarían de coincidir con el oráculo |
| Cambiar la partición (p. ej. por ruta) | `partitionBy` en el job + DDL | R6: las consultas por mes escanearían todo |
| Más concurrencia en reservas | `UVICORN_WORKERS`, `pool_size` en `app/core/database.py` | Conexiones de PostgreSQL (`max_connections=120`) |

Preguntas probables: por qué el UPDATE condicional no permite sobreventa (2.3); por qué un archivo por
mes (2.4, paso 8); qué pasa si EMR falla (`TERMINATE_CLUSTER`); por qué no hay caché (sección 6).

---

## 8. Revisión de cumplimiento (20-oct-2026)

### Parcial 2: requisitos verificados

| Req | Estado en local | Evidencia | Pendiente en AWS |
|---|---|---|---|
| R1 | Cumple | p95 = 0,03 s con 20 clientes (límite 1 s) | Repetir en la t3.small |
| R2 | Cumple | 5 rondas × 50 peticiones: 1 × 201 y 49 × 409; con K = 5, exactamente 5 | — |
| R3 | Cumple | 200 con la reserva, 404 si no existe | — |
| R4 | Cumple (emulado) | 1.977.131 filas = oráculo; ingresos por mes exactos; 24 particiones | Correr `run_emr_job.sh` |
| R5 | Cumple (emulado) | Columnas y tipos exactos, partición `month` | Ejecutar `create_tables.sql` |
| R6 | Cumple (emulado) | Top 10 idéntico al oráculo; una partición ≈ 0,8 MB | Bytes reales de Athena |
| R7 | Cumple (emulado) | 5 sondas correctas en < 0,2 s; cada llamada consulta el motor | Motor Athena probado con cliente simulado (`tests/test_athena_engine.py`), falta la prueba real |
| R8 | Cumple | Playwright: buscar → reservar → confirmación; el backend devuelve la reserva | — |
| R9 | Cumple | Panel = endpoint = oráculo (diferencia < 0,001) | — |
| R10–R12 | Cumple sobre el plan | 12 h normalizadas de EMR, 5 servicios, US$ 17,75 frente al límite de US$ 50 | Verificar con recursos reales |

Casos borde del contrato comprobados a mano: 404 si se reserva un vuelo inexistente, 422 con
parámetros de búsqueda o mes inválidos, `[]` si no hay vuelos, 409 si `flight_id` ya existe y 422
si la clase no es ECONOMY/BUSINESS.

### Parcial 1: sigue funcionando

| Qué | Resultado |
|---|---|
| `tests/test_api.py` (11 pruebas: búsqueda directa y con escala, reserva de uno y varios trayectos, cancelación con devolución de cupo, B2B con API key válida e inválida) | 11/11 |
| `scripts/test_all_endpoints.py` | Todos los endpoints responden 200/201 |
| `scripts/test_concurrency.py` (RNF-02) | 2 asientos, 20 peticiones: 2 × 201, 18 × 409, 0 % de sobreventa |
| ETL OLTP → OLAP (estrella): `setup_olap_database`, `generate_sample_bookings`, `etl_oltp_to_olap`, `verify_olap_queries` | Corre completo |
| Swagger: `/api/v1/docs` redirige a `/docs` | OK |

Para correr las pruebas del parcial 1 con el sistema arriba:

```bash
docker compose run --rm --no-deps -v "$PWD/tests:/workspace/tests" -v "$PWD/pytest.ini:/workspace/pytest.ini" api pytest -q tests
docker compose exec api python scripts/test_concurrency.py
```

### Diferencias que hay que explicar en el documento (no son errores del código)

- **Multi-AZ y autoescalado (RNF-03, RNF-04 del parcial 1) contra R11 del parcial 2.** El parcial 2
  prohíbe Multi-AZ y premia lo más barato. El documento debe decir que el diseño cambió a propósito:
  una EC2 sin Multi-AZ ni autoescalado, aceptando menos disponibilidad a cambio de costo.
- **RDS analítica + Glue ETL (sección 6 del parcial 1) contra S3 + EMR + Athena.** El análisis ya no
  vive en una segunda base PostgreSQL; el ETL del parcial 1 sigue en el repositorio como antecedente.
- **"Hasta 2 escalas" (RNF-01) y "fecha de retorno" (RF-01).** La API del parcial 1 busca vuelos
  directos y con **1** escala, y no maneja fecha de retorno. Esto viene del parcial 1 y el parcial 2
  no lo pide; basta con no afirmar lo contrario en el documento.
- **`bookings`:** el contrato dice "solo CONFIRMED" y el oráculo cuenta todas (sección 2.4).

## 9. Pendientes del equipo

- [ ] Poner la **semilla real** del equipo en `TEAM_SEED`, `local_harness/config.local.yaml` y
      `parcial2-harness/config.yaml` (ya creado: faltan semilla, IP del EC2 y bucket); regenerar datos y volver a correr el job.
- [ ] Desplegar en AWS (sección 5) y adjuntar el `report.md` **real** del harness.
- [ ] Diagrama de arquitectura para el documento (puede partir del de la sección 2.1).
- [ ] Anexo de *prompt log* (obligatorio).
- [ ] Ajustar `cost_projection.yaml` si el despliegue final difiere (R12 exige ±25 % frente a lo desplegado).
