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

    # Vuelos de demostración que se crean al arrancar (para probar el frontend a mano).
    DEMO_ROUTES: str = "BOG-MDE,MDE-BOG,BOG-CTG,CLO-CTG,BGA-BOG,BOG-SMR"
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

