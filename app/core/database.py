from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

# Engine configurado para alta concurrencia en entorno OLTP
engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """
    Inyector de dependencias para sesiones de base de datos en FastAPI.
    Asegura el cierre de la sesión tras cada petición.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

