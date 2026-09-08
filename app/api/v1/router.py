from fastapi import APIRouter
from app.api.v1.endpoints import flights, reservations, health

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(flights.router, prefix="/flights")
api_router.include_router(reservations.router, prefix="/reservations")

