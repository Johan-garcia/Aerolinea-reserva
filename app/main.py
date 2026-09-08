from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.router import api_router
from app.core.database import engine
from app.models.base import Base
# Importar modelos para que Base.metadata reconozca todas las tablas
import app.models  # noqa: F401

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "API del Sistema de Reservas de Vuelos para Aerolínea Regional. "
        "Soporta búsqueda de vuelos (directos y con escalas), creación de reservas multitrayecto, "
        "control de concurrencia pesimista para 0% de sobreventa, auditoría inmutable e integración B2B."
    ),
    version="1.0.0",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro de routers modulares v1
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {
        "message": f"Bienvenido a la API de {settings.PROJECT_NAME}",
        "docs": f"{settings.API_V1_PREFIX}/docs",
        "health": f"{settings.API_V1_PREFIX}/health",
    }

