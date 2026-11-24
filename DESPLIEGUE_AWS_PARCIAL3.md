# Despliegue del Parcial 3 en AWS (Learner Lab), paso a paso

Equipo **Wilches-García** · semilla **24306** · bucket `airline-wilches-garcia-24306` · región `us-east-1`.

Estado del código: en local el harness oficial del Parcial 3 da **70/70 con la semilla 24306**
(verificado el 24-nov-2026 con Kinesis simulado por `moto` y "Athena" con DuckDB). Falta correrlo en AWS.
Esta guía se hace en **una sesión del Lab (~1 h)**.

> Lo que todavía no se ha podido probar sin AWS y conviene vigilar: que el `LabRole` deje crear el stream de
> Kinesis, el workgroup de Athena y tablas en Glue; y que Athena lea bien los Parquet de la estrella. Si algo
> de eso falla, ver la tabla del final.

---

## 0. Qué se despliega

Se reutiliza todo lo del Parcial 2 y se agregan 3 cosas:

| Recurso | Parcial | Para qué |
|---|---|---|
| EC2 `airline-app` t3.small (Ubuntu 24.04, `LabInstanceProfile`, hop limit 2) | P2 | db + api + **worker** + frontend en Docker |
| Bucket `airline-wilches-garcia-24306` | P2 | lago: `curated/`, `athena-results/`, y ahora **`raw/events/`** (landing) y **`star/`** (estrella) |
| Base `airline_analytics` en Glue/Athena | P2 | histórico de reservas (EMR) |
| **Stream Kinesis `airline-events`** (1 shard, aprovisionado, 24 h) | **P3** | eventos de búsquedas, reservas y cancelaciones |
| **Workgroup Athena `airline-p3`** (límite 1 GB por consulta) | **P3** | consultas sobre la estrella (R10) |
| **Base `airline_star`** en Glue | **P3** | tablas de la estrella (las crea el worker en cada refresco) |

Flujo: la API publica cada acción en Kinesis → el **worker** (único consumidor) alimenta la vista en vivo
y escribe la landing zone en S3 → cada `STAR_REFRESH_MINUTES` (10) arma la estrella en Parquet y registra las
tablas en Athena.

---

## 1. Desde el portátil: subir el código

Lo que está en el commit local tiene que llegar a GitHub para que la EC2 lo descargue:

```bash
git push origin main
```

`ref/` (los CSV de las dimensiones con la semilla 24306) va en el commit: el worker los necesita y no son
secretos.

## 2. Iniciar el Lab y la EC2

1. AWS Academy → Learner Lab → **Start Lab** → esperar el círculo verde → **AWS**. Región **N. Virginia**.
2. **Si la EC2 `airline-app` del Parcial 2 todavía existe:** EC2 → seleccionarla → **Instance state → Start**.
   Saltar al paso 3.
3. **Si el Lab se reinició y no queda nada** (no hay EC2 ni bucket): seguir primero
   [`DESPLIEGUE_AWS.md`](DESPLIEGUE_AWS.md) pasos 2 a 6 (bucket, EC2, datos, EMR, Athena). Al clonar usen
   `main` (ya no hace falta la rama `parcial2-despliegue-aws`). Luego continúen aquí en el paso 3.

Conectarse: EC2 → `airline-app` → **Connect → EC2 Instance Connect → Connect**.

## 3. En la EC2: actualizar código y credenciales

```bash
cd ~/Aerolinea-reserva
git checkout main && git pull

# Las credenciales del Lab cambian en cada sesión: pegar de nuevo el bloque [default]
# de "AWS Details > AWS CLI > Show"
nano ~/.aws/credentials
aws sts get-caller-identity          # debe mostrar un ARN con "voclabs"
```

## 4. Preparación única del Parcial 3

```bash
export BUCKET=airline-wilches-garcia-24306

# 4.1 .env y contenedores base (reescribe .env con las variables del P2 y del P3)
bash aws/ec2/bootstrap.sh            # debe terminar con "OK: el backend puede llamar a Athena."

# 4.2 Workgroup airline-p3 (límite 1 GB), base airline_star y variables del P3 en .env
bash aws/p3/setup.sh

# 4.3 Comprobar que ref/ llegó con la semilla correcta
cat ref/SEED                         # 24306
grep seed parcial3-harness-estudiantes/config.yaml   # seed: 24306
```

Si `ref/` no estuviera (por ejemplo, si no se hizo el push): `bash aws/p3/generate_ref.sh 24306`.

## 5. Crear el stream y levantar todo

```bash
bash aws/p3/stream.sh create         # tabla: ACTIVE · PROVISIONED · 1 shard · 24 h · 0 consumidores EFO
sudo docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
sudo docker compose -f docker-compose.yml -f docker-compose.aws.yml ps   # los 4 contenedores Up; worker (healthy)
```

> El orden importa poco: si el stream no existe, el worker reintenta cada 30 s y empieza a leer cuando aparece.

## 6. Verificación manual (5 minutos)

```bash
DC="sudo docker compose -f docker-compose.yml -f docker-compose.aws.yml"
$DC exec worker curl -s localhost:8001/health    # "consumer": "reading 1 shard(s)" (no "disabled" ni "stream not found")
curl -s localhost:8000/admin/events-stats        # el publicador cuenta eventos enviados
```

1. Abrir `http://<IP>:3000/`, hacer una búsqueda, una reserva y cancelarla.
2. `curl -s localhost:8000/analytics/live` → los contadores de los últimos 5 min suben en ~1 s.
3. Después de ~60 s (`LANDING_FLUSH_SECONDS`): `aws s3 ls s3://$BUCKET/raw/events/ --recursive | tail` muestra archivos.
4. Forzar la estrella sin esperar 10 min: `curl -s -X POST localhost:8000/admin/refresh-star` y luego
   `curl -s localhost:8000/admin/refresh-status` → `SUCCEEDED`.
5. En la consola de Athena, workgroup **airline-p3**, base **airline_star**: `SELECT COUNT(*) FROM fact_search;`

Si todo esto funciona, el harness debería pasar.

## 7. Corrida oficial del harness

```bash
# 7.1 Arranque LIMPIO: borra stream, landing, estrella y checkpoint del worker, y los vuelve a crear.
#     Sin esto, los eventos de las pruebas (mismos event_id) se mezclan con los del profesor:
#     en local bajó a 49/70 sin limpiar y volvió a 70/70 limpiando.
bash aws/p3/reset.sh

# 7.2 Harness: escribe la IP y el bucket en el config.yaml, corre las pruebas y copia el reporte
bash aws/p3/run_harness.sh           # la primera vez instala python3-venv y dependencias (~2 min)
```

Resultado en `entrega/parcial3/report.md`. Subirlo al repo junto con el `config.yaml` (ya tiene la IP):

```bash
git add -f entrega/parcial3 parcial3-harness-estudiantes/config.yaml
git commit -m "entrega(parcial3): reporte del harness en AWS"
git push
```

Luego pegar el puntaje y las evidencias en la sección **6.2** de `DOCUMENTO_PARCIAL3.md`. Si algo sale
*failed* o *skipped*, explicar ahí por qué (lo pide la sección 6 del enunciado).

## 8. Al terminar la sesión: apagar

```bash
bash aws/p3/stream.sh delete         # un shard se cobra por hora que EXISTE (~US$ 0,015/h ≈ US$ 0,36/día)
bash aws/estado_aws.sh               # sin EMR activos, sin RDS/NAT/LB
```

EC2 → `airline-app` → **Instance state → Stop**. **No borren** el bucket, el workgroup ni las bases de Glue.

## 9. Ventana de calificación del profesor

El harness del profesor necesita el stream **creado** y el sistema arriba:

1. Start Lab → EC2 → **Start** `airline-app` (los contenedores arrancan solos).
2. En la EC2: pegar credenciales nuevas en `~/.aws/credentials`, luego `bash aws/p3/reset.sh`. Así queda el stream
   recién creado y la landing vacía, sin restos de nuestras pruebas.
3. La IP pública **cambia** en cada arranque: correr `bash aws/p3/run_harness.sh` (actualiza `config.yaml`
   con la IP nueva y re-verifica), hacer commit y push del `config.yaml`.
4. Dejar el Lab encendido durante toda la ventana (las sesiones duran 4 h).

---

## 10. Si algo falla

| Síntoma | Causa probable | Arreglo |
|---|---|---|
| `AccessDenied` / `ExpiredToken` en la CLI | Credenciales del Lab vencidas | Pegar de nuevo `~/.aws/credentials` |
| `stream.sh create` da `AccessDenied` | El `LabRole` no permite Kinesis en esa cuenta | Anotarlo en 6.2; revisar en IAM → Roles → LabRole qué acciones `kinesis:*` tiene |
| `setup.sh` falla al crear el workgroup | Sin permiso `athena:CreateWorkGroup` | Crear el workgroup a mano en la consola de Athena (nombre `airline-p3`, *Bytes scanned cutoff* 1 GB, resultados en `s3://$BUCKET/athena-results/`) |
| worker en `Restarting` | Error al arrancar | `$DC logs --tail 50 worker` |
| `/health` del worker dice `"consumer": "disabled"` | `KINESIS_STREAM` vacío en `.env` | Repetir `bash aws/p3/setup.sh` y `$DC up -d worker` |
| La landing en S3 sigue vacía | El worker no tiene credenciales del rol | Hop limit en 2 (ver `DESPLIEGUE_AWS.md` paso 3) y `$DC restart worker api` |
| `refresh-status` en `FAILED` | DDL de Athena o lectura del Parquet | `$DC logs worker \| grep -i athena`; el mensaje de Athena dice la columna o el tipo que no le gusta |
| R7, R8 o R9 fallan con números raros | Quedaron eventos viejos en la landing | `bash aws/p3/reset.sh` y volver a correr el harness |
| R2 falla por latencia | La API espera a Kinesis | Revisar `curl -s localhost:8000/admin/events-stats` (la publicación es en segundo plano; si hay cola muy grande, el stream no existe) |
| R11 falla | El stream no existe, tiene más de 1 shard o es *on-demand* | `bash aws/p3/stream.sh delete && bash aws/p3/stream.sh create` |
| R12 falla | Hay EC2 o EMR de más encendidos | `bash aws/estado_aws.sh` y detener lo que sobre |

Diagnóstico general: `$DC logs -f api worker`.
