"""
Crea vuelos de demostración (tabla flights del Parcial 2) para los próximos DEMO_DAYS días,
de modo que el buscador del frontend tenga resultados al probarlo a mano.
Es idempotente: usa ON CONFLICT DO NOTHING sobre flight_id.
"""
import sys
import zlib
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.crud.crud_contract import crear_vuelo
from app.models import Base
from app.schemas.contract import FlightCreate

SALIDAS = ["0640", "1215", "1830"]


def main():
    Base.metadata.create_all(bind=engine)
    rutas = [r.strip().upper() for r in settings.DEMO_ROUTES.split(",") if r.strip()]
    hoy = date.today()
    creados = 0
    with SessionLocal() as db:
        for ruta in rutas:
            # Precio base estable por ruta (no aleatorio entre reinicios).
            base = 9_000 + (zlib.crc32(ruta.encode()) % 40) * 500  # USD 90-290 en centavos
            for d in range(1, settings.DEMO_DAYS + 1):
                dia = hoy + timedelta(days=d)
                for i, hora in enumerate(SALIDAS):
                    fid = f"DM{ruta.replace('-', '')}{dia:%m%d}{hora}"
                    data = FlightCreate(flight_id=fid, route=ruta, flight_date=dia,
                                        capacity=180, price_cents=base + i * 2_500)
                    if crear_vuelo(db, data) is not None:
                        creados += 1
    print(f"Vuelos demo: {creados} nuevos ({len(rutas)} rutas x {settings.DEMO_DAYS} días x {len(SALIDAS)})")


if __name__ == "__main__":
    main()
