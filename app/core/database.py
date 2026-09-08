from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

# Engine configurado para alta concurrencia en entorno OLTP
is_sqlite = settings.sync_database_url.startswith("sqlite")
engine_kwargs = {"pool_pre_ping": True}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 10,
        "pool_recycle": 3600,
    })

from sqlalchemy import event

engine = create_engine(
    settings.sync_database_url,
    **engine_kwargs,
)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    @event.listens_for(engine, "begin")
    def do_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

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

