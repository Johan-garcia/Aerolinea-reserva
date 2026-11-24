"""
SQL (DuckDB) del ETL landing zone -> esquema estrella. Cada bloque es una tabla del contrato
(parcial3-harness-estudiantes/contract/STAR.md) más los atributos extra que agregamos para
responder las preguntas de negocio Q1-Q8.

Orden: events (dedup) -> dim_date -> dim_fare_class -> dim_route (SCD2) -> fact_search -> fact_booking_event.
"""

# 1) Eventos limpios: una fila por event_id (dedup, gana la última copia en llegar), fecha y mes tomados de event_ts (hora en que
#    OCURRIÓ, no de llegada). Así un evento tardío o desordenado cae en la misma fecha que si hubiera
#    llegado a tiempo. Los eventos sin event_ts válido se descartan (se reportan en las métricas).
EVENTS = r"""
CREATE OR REPLACE TABLE events AS
SELECT * EXCLUDE (rn)
FROM (
    SELECT *,
           CAST(substr(event_ts, 1, 10) AS DATE)                    AS event_date,
           CAST(replace(substr(event_ts, 1, 10), '-', '') AS INTEGER) AS date_key,
           substr(event_ts, 1, 7)                                   AS month,
           -- Un reintento reusa el event_id con el mismo contenido: da igual cuál copia quede.
           -- Se conserva la ÚLTIMA en llegar (semántica de upsert por event_id).
           row_number() OVER (PARTITION BY event_id ORDER BY arrival_order DESC) AS rn
    FROM raw_events
    WHERE event_id IS NOT NULL
      AND regexp_full_match(coalesce(event_ts, ''), '\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
      AND event_type IN ('search_performed', 'reservation_created', 'reservation_cancelled')
)
WHERE rn = 1
"""

# 2) dim_date enriquecida (2023-01-01 .. 2027-12-31). weekday ISO: 1 = lunes .. 7 = domingo.
#    Puente festivo (is_long_weekend): un festivo que cae viernes o lunes forma un fin de semana de
#    tres días; se marcan ese festivo y el sábado y domingo contiguos.
DIM_DATE = r"""
CREATE OR REPLACE TABLE holidays AS
SELECT CAST("date" AS DATE) AS d, string_agg(holiday_name, ' / ' ORDER BY holiday_name) AS holiday_name
FROM ref_holidays GROUP BY 1;

CREATE OR REPLACE TABLE dim_date AS
WITH days AS (
    SELECT CAST(range AS DATE) AS d
    FROM range(DATE '2023-01-01', DATE '2028-01-01', INTERVAL 1 DAY)
),
flags AS (
    SELECT d,
           isodow(d)                                     AS dow,
           d IN (SELECT d FROM holidays)                 AS hol,
           (d - 1) IN (SELECT d FROM holidays)           AS hol_m1,
           (d - 2) IN (SELECT d FROM holidays)           AS hol_m2,
           (d + 1) IN (SELECT d FROM holidays)           AS hol_p1,
           (d + 2) IN (SELECT d FROM holidays)           AS hol_p2
    FROM days
)
SELECT
    CAST(strftime(f.d, '%Y%m%d') AS INTEGER)              AS date_key,
    f.d                                                   AS full_date,
    CAST(year(f.d) AS INTEGER)                            AS year,
    CAST(month(f.d) AS INTEGER)                           AS month,
    CAST(quarter(f.d) AS INTEGER)                         AS quarter,
    CAST(f.dow AS INTEGER)                                AS weekday,
    ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][f.dow] AS weekday_name,
    f.dow >= 6                                            AS is_weekend,
    f.hol                                                 AS is_holiday,
    coalesce(h.holiday_name, '')                          AS holiday_name,
    CASE f.dow
        WHEN 1 THEN f.hol                                 -- lunes festivo
        WHEN 5 THEN f.hol                                 -- viernes festivo
        WHEN 6 THEN f.hol_m1 OR f.hol_p2                  -- sábado: viernes anterior o lunes siguiente
        WHEN 7 THEN f.hol_m2 OR f.hol_p1                  -- domingo: viernes o lunes del mismo puente
        ELSE FALSE
    END                                                   AS is_long_weekend,
    -- atributos extra (jerarquía año > trimestre > mes > día y etiquetas para reportes)
    strftime(f.d, '%Y-%m')                                AS year_month,
    ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre',
     'Noviembre','Diciembre'][month(f.d)]                 AS month_name_es,
    CAST(day(f.d) AS INTEGER)                             AS day_of_month,
    CAST(weekofyear(f.d) AS INTEGER)                      AS iso_week,
    NOT (f.dow >= 6 OR f.hol)                             AS is_business_day
FROM flags f
LEFT JOIN holidays h ON h.d = f.d
ORDER BY 1
"""

DIM_FARE_CLASS = r"""
CREATE OR REPLACE TABLE dim_fare_class AS
SELECT * FROM (VALUES
    (CAST(0 AS INTEGER), 'UNKNOWN',  'Desconocida', 'UNKNOWN', FALSE),
    (CAST(1 AS INTEGER), 'ECONOMY',  'Económica',   'MAIN',    FALSE),
    (CAST(2 AS INTEGER), 'BUSINESS', 'Ejecutiva',   'PREMIUM', TRUE)
) AS t(fare_class_key, fare_class, fare_class_name_es, cabin, is_premium)
"""

# 3) dim_route, SCD tipo 2: una fila por versión de la categoría de la ruta.
#    valid_from inclusivo, valid_to exclusivo (la vigente termina en 9999-12-31 con is_current).
#    Claves sustitutas estables: 1..N para las rutas de referencia (orden ruta, valid_from);
#    10001.. para "miembros inferidos" (rutas que aparecen en eventos pero no en la referencia) y
#    0 = UNKNOWN. Así ninguna fila de hechos queda huérfana (R6) y las claves de referencia no
#    cambian cuando aparece una ruta nueva.
DIM_ROUTE = r"""
CREATE OR REPLACE TABLE dim_route AS
WITH hist AS (
    SELECT upper(replace(route, ' ', ''))           AS route,
           upper(trim(route_category))              AS route_category,
           CAST(effective_date AS DATE)             AS valid_from
    FROM ref_route_category_history
),
versions AS (
    SELECT h.route, h.route_category, h.valid_from,
           coalesce(lead(h.valid_from) OVER w, DATE '9999-12-31') AS valid_to,
           lead(h.valid_from) OVER w IS NULL                       AS is_current,
           CAST(row_number() OVER w AS INTEGER)                    AS version
    FROM hist h
    WINDOW w AS (PARTITION BY h.route ORDER BY h.valid_from)
),
ref AS (
    SELECT CAST(row_number() OVER (ORDER BY v.route, v.valid_from) AS INTEGER) AS route_key,
           v.route,
           coalesce(r.origin, split_part(v.route, '-', 1))      AS origin,
           coalesce(r.destination, split_part(v.route, '-', 2)) AS destination,
           coalesce(r.region, 'UNKNOWN')                        AS region,
           v.route_category, v.valid_from, v.valid_to, v.is_current, v.version,
           FALSE AS is_inferred
    FROM versions v
    LEFT JOIN ref_routes r ON upper(r.route) = v.route
),
seen AS (
    SELECT DISTINCT route FROM (
        SELECT upper(origin) || '-' || upper(destination) AS route FROM events
        WHERE event_type = 'search_performed' AND origin IS NOT NULL AND destination IS NOT NULL
        UNION ALL
        SELECT upper(replace(route, ' ', '')) FROM events
        WHERE event_type <> 'search_performed' AND route IS NOT NULL
    )
    WHERE route NOT IN (SELECT route FROM ref)
),
inferred AS (
    SELECT CAST(10000 + row_number() OVER (ORDER BY route) AS INTEGER) AS route_key,
           route, split_part(route, '-', 1), split_part(route, '-', 2), 'UNKNOWN', 'UNKNOWN',
           DATE '1900-01-01', DATE '9999-12-31', TRUE, CAST(1 AS INTEGER), TRUE
    FROM seen
)
SELECT * FROM ref
UNION ALL SELECT * FROM inferred
UNION ALL SELECT CAST(0 AS INTEGER), 'UNKNOWN', 'UNK', 'UNK', 'UNKNOWN', 'UNKNOWN',
                 DATE '1900-01-01', DATE '9999-12-31', TRUE, CAST(1 AS INTEGER), TRUE
ORDER BY route_key
"""

# 4) Hechos. route_key = versión de la ruta VIGENTE EN LA FECHA DEL EVENTO (as-of join):
#    event_date >= valid_from AND event_date < valid_to. Un evento tardío usa su propia fecha,
#    así que toma la versión correcta aunque llegue después del cambio de categoría.
FACT_SEARCH = r"""
CREATE OR REPLACE TABLE fact_search AS
SELECT e.event_id,
       e.date_key,
       coalesce(r.route_key, 0)                              AS route_key,
       CAST(coalesce(e.results_count, 0) AS INTEGER)         AS results_count,
       CAST(1 AS INTEGER)                                    AS searches,
       -- extras: dimensiones degeneradas y una medida de anticipación
       e.session_id,
       e.event_ts,
       TRY_CAST(e.travel_date AS DATE)                       AS travel_date,
       CAST(TRY_CAST(e.travel_date AS DATE) - e.event_date AS INTEGER) AS days_in_advance,
       (coalesce(e.results_count, 0) = 0)                    AS zero_results,
       e.month                                               AS month
FROM events e
LEFT JOIN dim_route r
       ON r.route = upper(e.origin) || '-' || upper(e.destination)
      AND e.event_date >= r.valid_from AND e.event_date < r.valid_to
WHERE e.event_type = 'search_performed'
"""

FACT_BOOKING = r"""
CREATE OR REPLACE TABLE fact_booking_event AS
SELECT e.event_id,
       e.date_key,
       coalesce(r.route_key, 0)                                               AS route_key,
       coalesce(c.fare_class_key, 0)                                          AS fare_class_key,
       e.reservation_id,
       e.event_type,
       CAST(CASE WHEN e.event_type = 'reservation_created'   THEN 1 ELSE 0 END AS INTEGER) AS bookings,
       CAST(CASE WHEN e.event_type = 'reservation_cancelled' THEN 1 ELSE 0 END AS INTEGER) AS cancellations,
       CAST(CASE WHEN e.event_type = 'reservation_created' THEN e.price_cents
                 ELSE -e.price_cents END AS BIGINT)                           AS revenue_cents,
       -- extras
       e.flight_id,
       TRY_CAST(e.flight_date AS DATE)                                        AS flight_date,
       CAST(TRY_CAST(e.flight_date AS DATE) - e.event_date AS INTEGER)         AS days_in_advance,
       CAST(abs(e.price_cents) AS BIGINT)                                     AS ticket_price_cents,
       e.event_ts,
       e.month
FROM events e
LEFT JOIN dim_route r
       ON r.route = upper(replace(e.route, ' ', ''))
      AND e.event_date >= r.valid_from AND e.event_date < r.valid_to
LEFT JOIN dim_fare_class c ON c.fare_class = upper(e.fare_class)
WHERE e.event_type IN ('reservation_created', 'reservation_cancelled')
"""

# Tablas que se publican y si van particionadas por mes (solo fact_search lo exige el contrato).
TABLES = [
    ("dim_date", None),
    ("dim_fare_class", None),
    ("dim_route", None),
    ("fact_search", "month"),
    ("fact_booking_event", None),
]
