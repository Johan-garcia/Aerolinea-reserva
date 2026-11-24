# Harness del Parcial 3 en local (sin AWS)

Corre el harness oficial (`parcial3-harness-estudiantes/`, sin modificarlo) contra la API y el worker reales,
con Kinesis simulado por `moto`, la landing zone y la estrella en disco y "Athena" con DuckDB (`local_aws.py`).

```bash
# 1. Dependencias (un venv aparte)
python3 -m venv /tmp/p3 && /tmp/p3/bin/pip install -r requirements.txt "moto[server,kinesis]" pyyaml pandas numpy pyarrow
# 2. PostgreSQL local en el puerto 5544 (o docker compose up -d db y usar 5432)
# 3. Variables comunes
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
export AWS_ENDPOINT_URL=http://127.0.0.1:5055            # moto
export DATABASE_URL=postgresql://postgres@127.0.0.1:5544/aerolinea_db
export KINESIS_STREAM=airline-events WORKER_URL=http://127.0.0.1:8001 STAR_REFRESH_MINUTES=0 LANDING_FLUSH_SECONDS=20
export LOCAL_LAKE=/tmp/p3lake STATE_DIR=/tmp/p3state REF_DIR=$PWD/ref
# 4. Levantar moto, crear el stream, la API y el worker
/tmp/p3/bin/moto_server -p 5055 &
/tmp/p3/bin/python -c "import boto3; boto3.client('kinesis').create_stream(StreamName='airline-events', ShardCount=1)"
/tmp/p3/bin/python scripts/seed_data.py
/tmp/p3/bin/uvicorn app.main:app --port 8000 --workers 2 --no-access-log &
/tmp/p3/bin/python -m app.worker.main &
# 5. Harness (TEAM_SEED = la semilla de ref/; PROBE_SALT simula los datos secretos del profesor)
TEAM_SEED=$(cat ref/SEED) /tmp/p3/bin/python local_harness_p3/run_local.py
```

El reporte queda en `local_harness_p3/report.md`. Para simular la sustentación con otros datos, primero hay que
arrancar limpio (detener el worker, borrar y recrear el stream, borrar `$LOCAL_LAKE` y `$STATE_DIR`, encender el
worker) y luego correr con `PROBE_SALT=7`. Sin limpiar, los replays anteriores con los mismos `event_id` se
mezclan y R7-R9 fallan (ver DOCUMENTO_PARCIAL3.md, 5.7).
