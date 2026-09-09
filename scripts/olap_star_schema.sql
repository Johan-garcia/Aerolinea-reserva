-- ============================================================================
-- PROYECTO: SISTEMA DE RESERVAS DE VUELOS - AEROLÍNEA REGIONAL
-- FASE 5.6: MODELO DIMENSIONAL (MODELO EN ESTRELLA / STAR SCHEMA)
-- MOTOR: PostgreSQL (Amazon RDS Analítico)
-- ============================================================================

-- 0. Limpieza previa en caso de regeneración de esquema
DROP TABLE IF EXISTS fact_reservas CASCADE;
DROP TABLE IF EXISTS dim_pasajero CASCADE;
DROP TABLE IF EXISTS dim_vuelo_ruta CASCADE;
DROP TABLE IF EXISTS dim_tarifa CASCADE;
DROP TABLE IF EXISTS dim_agencia CASCADE;

-- ============================================================================
-- 1. TABLA DE DIMENSIÓN: dim_pasajero
-- ============================================================================
CREATE TABLE dim_pasajero (
    id_dim_pasajero SERIAL PRIMARY KEY,
    id_pasajero_origen INT NOT NULL,
    tipo_documento VARCHAR(20) NOT NULL,
    numero_documento VARCHAR(50) NOT NULL,
    nombres VARCHAR(100) NOT NULL,
    apellidos VARCHAR(100) NOT NULL,
    nombre_completo VARCHAR(250) NOT NULL,
    email VARCHAR(150) NOT NULL,
    telefono VARCHAR(50),
    fecha_carga TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dim_pasajero_origen ON dim_pasajero(id_pasajero_origen);
CREATE INDEX idx_dim_pasajero_doc ON dim_pasajero(tipo_documento, numero_documento);

-- ============================================================================
-- 2. TABLA DE DIMENSIÓN: dim_vuelo_ruta
-- Desnormaliza: Vuelos Programados, Rutas, Aeropuertos Origen/Destino y Aviones
-- ============================================================================
CREATE TABLE dim_vuelo_ruta (
    id_dim_vuelo_ruta SERIAL PRIMARY KEY,
    id_instancia_vuelo_origen INT NOT NULL,
    codigo_vuelo VARCHAR(20) NOT NULL,
    id_aeropuerto_origen VARCHAR(3) NOT NULL,
    aeropuerto_origen_nombre VARCHAR(150) NOT NULL,
    aeropuerto_origen_ciudad VARCHAR(100) NOT NULL,
    aeropuerto_origen_pais VARCHAR(100) NOT NULL,
    id_aeropuerto_destino VARCHAR(3) NOT NULL,
    aeropuerto_destino_nombre VARCHAR(150) NOT NULL,
    aeropuerto_destino_ciudad VARCHAR(100) NOT NULL,
    aeropuerto_destino_pais VARCHAR(100) NOT NULL,
    codigo_ruta VARCHAR(10) NOT NULL,             -- Ej: BOG-MDE
    nombre_ruta VARCHAR(200) NOT NULL,            -- Ej: Bogotá -> Medellín
    distancia_km INT NOT NULL,
    hora_salida_programada TIME NOT NULL,
    hora_llegada_programada TIME NOT NULL,
    fecha_hora_salida TIMESTAMP WITH TIME ZONE NOT NULL,
    fecha_salida DATE NOT NULL,
    avion_modelo VARCHAR(100) NOT NULL,
    avion_capacidad_total INT NOT NULL,
    estado_instancia VARCHAR(50) NOT NULL,
    fecha_carga TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dim_vuelo_instancia ON dim_vuelo_ruta(id_instancia_vuelo_origen);
CREATE INDEX idx_dim_vuelo_ruta_cod ON dim_vuelo_ruta(codigo_ruta);
CREATE INDEX idx_dim_vuelo_fecha ON dim_vuelo_ruta(fecha_salida);

-- ============================================================================
-- 3. TABLA DE DIMENSIÓN: dim_tarifa
-- ============================================================================
CREATE TABLE dim_tarifa (
    id_dim_tarifa SERIAL PRIMARY KEY,
    id_tarifa_origen INT NOT NULL,
    clase VARCHAR(50) NOT NULL,                    -- Económica / Ejecutiva
    tipo_regla VARCHAR(50) NOT NULL,               -- Promocional / Flexible
    porcentaje_reembolso NUMERIC(5, 2) NOT NULL,
    descripcion_tarifa VARCHAR(150) NOT NULL,      -- Ej: Económica - Promocional (0% Reembolso)
    fecha_carga TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dim_tarifa_origen ON dim_tarifa(id_tarifa_origen);

-- ============================================================================
-- 4. TABLA DE DIMENSIÓN: dim_agencia
-- Contempla tanto Agencias Aliadas B2B como el Canal Directo (Web de la aerolínea)
-- ============================================================================
CREATE TABLE dim_agencia (
    id_dim_agencia SERIAL PRIMARY KEY,
    id_agencia_origen INT NOT NULL,                -- -1 para Venta Directa Web
    nombre_agencia VARCHAR(150) NOT NULL,
    codigo_api_key VARCHAR(100),
    porcentaje_comision NUMERIC(5, 2) NOT NULL,
    canal_venta VARCHAR(50) NOT NULL,              -- 'Directo Web' / 'Agencia B2B'
    fecha_carga TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dim_agencia_origen ON dim_agencia(id_agencia_origen);

-- Inserción de registro predeterminado para ventas directas sin agencia
INSERT INTO dim_agencia (id_agencia_origen, nombre_agencia, codigo_api_key, porcentaje_comision, canal_venta)
VALUES (-1, 'Venta Directa Sitio Web', 'DIRECT-WEB-CHANNEL', 0.00, 'Directo Web');

-- ============================================================================
-- 5. TABLA DE HECHOS: fact_reservas
-- Grano: 1 fila por trayecto vendido en una reserva
-- ============================================================================
CREATE TABLE fact_reservas (
    id_fact_reserva SERIAL PRIMARY KEY,
    id_reserva_origen INT NOT NULL,
    id_detalle_origen INT NOT NULL,
    codigo_pnr VARCHAR(10) NOT NULL,
    
    -- Claves Foráneas a Dimensiones (Surrogate Keys)
    id_dim_pasajero INT NOT NULL REFERENCES dim_pasajero(id_dim_pasajero),
    id_dim_vuelo_ruta INT NOT NULL REFERENCES dim_vuelo_ruta(id_dim_vuelo_ruta),
    id_dim_tarifa INT NOT NULL REFERENCES dim_tarifa(id_dim_tarifa),
    id_dim_agencia INT NOT NULL REFERENCES dim_agencia(id_dim_agencia),
    
    -- Atributos de Degenerate Dimension y Fechas
    fecha_reserva TIMESTAMP WITH TIME ZONE NOT NULL,
    fecha_reserva_date DATE NOT NULL,
    estado_reserva VARCHAR(50) NOT NULL,           -- Pendiente, Confirmada, Cancelada
    estado_trayecto VARCHAR(50) NOT NULL,          -- Confirmado, Cancelado, Volado
    metodo_pago VARCHAR(50) DEFAULT 'Sin Pago',
    estado_pago VARCHAR(50) DEFAULT 'Sin Pago',
    numero_asiento VARCHAR(10),
    
    -- Métricas y Hechos Numéricos Aditivos
    precio_boleto NUMERIC(12, 2) NOT NULL,
    monto_comision NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    monto_neto_aerolinea NUMERIC(12, 2) NOT NULL,
    cantidad_asientos INT NOT NULL DEFAULT 1,
    es_confirmada INT NOT NULL DEFAULT 1,          -- 1 si Confirmada, 0 si no
    es_cancelada INT NOT NULL DEFAULT 0,           -- 1 si Cancelada, 0 si no
    dias_anticipacion_compra INT NOT NULL DEFAULT 0,
    
    fecha_carga TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_fact_pnr ON fact_reservas(codigo_pnr);
CREATE INDEX idx_fact_dim_pasajero ON fact_reservas(id_dim_pasajero);
CREATE INDEX idx_fact_dim_vuelo ON fact_reservas(id_dim_vuelo_ruta);
CREATE INDEX idx_fact_dim_tarifa ON fact_reservas(id_dim_tarifa);
CREATE INDEX idx_fact_dim_agencia ON fact_reservas(id_dim_agencia);
CREATE INDEX idx_fact_fecha_reserva ON fact_reservas(fecha_reserva_date);
CREATE INDEX idx_fact_estado ON fact_reservas(estado_reserva);
