from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.router import api_router
from app.api.contract import router as contract_router
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
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Contrato del Parcial 2 en la raíz (lo que consumen el harness y el frontend)
app.include_router(contract_router)

# Registro de routers modulares v1 (Parcial 1)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {
        "message": f"Bienvenido a la API de {settings.PROJECT_NAME}",
        "docs": "/docs",
        "health": "/health",
    }



# Compatibilidad con el Parcial 1: la documentación vivía en /api/v1/docs y /api/v1/redoc.
@app.get(f"{settings.API_V1_PREFIX}/docs", include_in_schema=False)
def docs_v1():
    return RedirectResponse("/docs")


@app.get(f"{settings.API_V1_PREFIX}/redoc", include_in_schema=False)
def redoc_v1():
    return RedirectResponse("/redoc")
