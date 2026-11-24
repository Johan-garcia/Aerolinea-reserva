from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Regional Airline Booking System"
    API_V1_PREFIX: str = "/api/v1"

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aerolinea_db"

    DATABASE_URL: Optional[str] = None

    # --- Parcial 2: capa analítica -------------------------------------------------
    # "duckdb" (local: lee el Parquet que produce el job PySpark) o "athena" (AWS).
    ANALYTICS_ENGINE: str = "duckdb"
    LAKE_PATH: str = "/data/lake"            # raíz del "S3 local" (solo duckdb)
    DETAIL_TABLE: str = "reservations_curated"
    METRICS_TABLE: str = "route_month_metrics"
    ATHENA_DATABASE: str = "airline_analytics"
    ATHENA_WORKGROUP: str = "primary"
    ATHENA_OUTPUT: Optional[str] = None      # s3://bucket/athena-results/ si el workgroup no tiene default
    AWS_REGION: str = "us-east-1"
    ANALYTICS_TIMEOUT_SECONDS: float = 9.0   # R7 exige respuesta en <= 10 s
    ANALYTICS_CACHE_TTL_SECONDS: int = 0     # >0 activa caché en memoria; la 1a consulta siempre va al motor

    # --- Parcial 3: eventos, vista en vivo y esquema estrella ---------------------
    # Sin KINESIS_STREAM el backend no publica eventos (desarrollo local sin AWS).
    KINESIS_STREAM: str = ""
    EVENTS_QUEUE_MAX: int = 20000            # búsquedas en cola; si se llena se descartan (nunca las reservas)
    EVENTS_BATCH_WAIT_SECONDS: float = 0.2   # cuánto espera el publicador para armar un lote de PutRecords
    WORKER_URL: str = "http://worker:8001"   # proceso consumidor: vista en vivo + landing + ETL de la estrella

    # Landing zone y estrella (los usa el worker)
    RAW_EVENTS_URI: str = ""                 # s3://BUCKET/raw/events/   (vacío = carpeta local LOCAL_LAKE/raw/events)
    STAR_URI: str = ""                       # s3://BUCKET/star/         (vacío = carpeta local LOCAL_LAKE/star)
    LOCAL_LAKE: str = "/data/lake/p3"
    REF_DIR: str = "/workspace/ref"          # routes_ref.csv, route_category_history.csv, holidays_ref.csv
    STATE_DIR: str = "/state"                # checkpoint del consumidor + caché del raw descargado
    STAR_DATABASE: str = "airline_star"
    STAR_WORKGROUP: str = "airline-p3"
    LANDING_FLUSH_SECONDS: int = 60          # el raw llega a S3 en <= ~1 min (R4 exige <= 5 min)
    LANDING_FLUSH_RECORDS: int = 5000
    STAR_REFRESH_MINUTES: int = 10           # micro-lote programado; 0 = solo bajo demanda
    LIVE_RETENTION_MINUTES: int = 60         # cuántos minutos de contadores guarda la vista en vivo

    # Vuelos de demostración que se crean al arrancar (para probar el frontend a mano).
    DEMO_ROUTES: str = "BOG-CTG,CTG-MDE,MDE-CUC,CTG-SMR,BAQ-BGA,LET-BAQ"
    DEMO_DAYS: int = 30

    @property
    def sync_database_url(self) -> str:
        # SQLAlchemy 2.1 usa psycopg (v3) por defecto con "postgresql://"; el proyecto usa psycopg2.
        if self.DATABASE_URL:
            if self.DATABASE_URL.startswith("postgresql://"):
                return "postgresql+psycopg2://" + self.DATABASE_URL[len("postgresql://"):]
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

