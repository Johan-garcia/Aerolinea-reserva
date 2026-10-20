# Despliegue del Parcial 2 en AWS (Learner Lab), paso a paso

Todo el código ya funciona: en local el harness oficial da **70/70** (verificado el 20-oct-2026 con
la semilla 24306; el job PySpark coincide fila por fila con el oráculo del profesor). Lo que falta es
montarlo en AWS y correr el harness allá. Esta guía está pensada para hacerse **en una sola sesión
del Lab (≈ 1,5 h)** y gastar **menos de US$ 2**.

## 0. Antes de empezar: qué NO se vuelve a crear del Parcial 1

El Parcial 2 premia lo más barato (R11, R12) y el Parcial 1 fue lo que se comió los créditos.
**No creen nada de esto:**

| Del Parcial 1 | Por qué no | Qué lo reemplaza |
|---|---|---|
| VPC propia Multi-AZ con subredes privadas | Innecesaria; la NAT Gateway cuesta ~US$ 33/mes y R11 la prohíbe | VPC por defecto |
| RDS PostgreSQL Multi-AZ | R11 prohíbe Multi-AZ; RDS cuesta ~US$ 14+/mes | PostgreSQL en contenedor dentro de la EC2 |
| RDS OLAP + Glue ETL job + crawlers | El análisis ahora va por S3 + EMR + Athena | `route_month_metrics` en Parquet + Athena |
| pgAdmin | No lo pide nadie | `docker compose exec db psql` si hace falta |

El código del Parcial 1 (API `/api/v1`, ETL a estrella) se queda en el repo como antecedente; no se despliega aparte.

**Lo que sí se crea (5 servicios):** 1 bucket S3, 1 EC2 t3.small, 1 cluster EMR que se apaga solo,
2 tablas en Glue Data Catalog y consultas Athena.

**Regla de oro del presupuesto:** al terminar cada sesión corran `bash aws/estado_aws.sh` y detengan la EC2.

---

## 1. Iniciar el Lab

1. AWS Academy → Learner Lab → **Start Lab**; esperar el círculo verde → **AWS**.
2. Confirmar región **N. Virginia (us-east-1)** arriba a la derecha.
3. En **AWS Details → AWS CLI → Show**: dejen esa ventana a mano; esas credenciales se pegan en el paso 3.
   Cambian en cada sesión.

## 2. Crear el bucket S3

S3 → **Create bucket** → nombre `airline-wilches-garcia-24306` (debe ser único en el mundo; si ya
existe, añadan un sufijo) → región us-east-1 → dejar todo por defecto → **Create**.

En el resto de la guía: `BUCKET=airline-wilches-garcia-24306` (cámbienlo si usaron otro nombre).

## 3. Lanzar la EC2

EC2 → **Launch instance**:

| Campo | Valor |
|---|---|
| Name | `airline-app` |
| AMI | **Ubuntu Server 24.04 LTS** (x86_64) |
| Instance type | **t3.small** |
| Key pair | `vockey` |
| Network | VPC por defecto, *Auto-assign public IP*: **Enable** |
| Security group (nuevo) `airline-sg` | Entrada: TCP **3000** desde 0.0.0.0/0 · TCP **8000** desde 0.0.0.0/0 · TCP **22** desde *My IP* y desde `18.206.107.24/29` (rango de EC2 Instance Connect en us-east-1) |
| Storage | **20 GiB gp3** |
| Advanced details → IAM instance profile | **LabInstanceProfile** |
| Advanced details → Metadata response hop limit | **2** (sin esto el contenedor del backend no obtiene credenciales para Athena) |

**Launch**. Cuando esté *Running*: seleccionarla → **Connect → EC2 Instance Connect → Connect**
(se abre una terminal en el navegador). Alternativa: `ssh -i labsuser.pem ubuntu@<IP>` con el
`labsuser.pem` que se descarga en AWS Details.

En esa terminal:

```bash
git clone https://github.com/Johan-garcia/Aerolinea-reserva.git
cd Aerolinea-reserva

# Credenciales del Lab para la AWS CLI (las usan EMR, Athena y el harness; los contenedores NO las usan)
mkdir -p ~/.aws
nano ~/.aws/credentials        # pegar el bloque [default] de "AWS Details > AWS CLI", guardar (Ctrl+O, Enter, Ctrl+X)
printf "[default]\nregion = us-east-1\n" > ~/.aws/config
aws sts get-caller-identity    # debe mostrar el ARN con "voclabs"

# Docker + contenedores (3-5 min la primera vez)
BUCKET=airline-wilches-garcia-24306 bash aws/ec2/bootstrap.sh
```

Al final imprime las URLs y **“OK: el backend puede llamar a Athena.”** Si sale el error del rol,
sigue las dos instrucciones que imprime (perfil IAM y hop limit).

En este momento ya funcionan R1, R2, R3 y la página de clientes: abran `http://<IP>:3000/` y hagan
una reserva de prueba (hay vuelos demo BOG→CTG, CTG→MDE, etc. para los próximos 30 días).

## 4. Generar los datos crudos (en la EC2)

```bash
sudo TEAM_SEED=24306 docker compose --profile batch run --rm datagen
wc -l data/raw/reservations.csv       # 2046431 (2.046.430 filas + encabezado)
```

> El enunciado recomienda probar con una muestra antes de la corrida completa. Ya lo hicimos en
> local con los 2 M de filas y el resultado coincide con el oráculo, así que **en EMR vamos directo a
> la corrida completa**: una corrida de muestra cuesta casi lo mismo (lo caro es arrancar el cluster).

## 5. Job PySpark en EMR (R4, R10)

```bash
BUCKET=airline-wilches-garcia-24306 bash aws/emr/run_emr_job.sh
```

Qué hace: sube `data/raw` y el job a S3, crea 1 master + 2 core **m4.large** con `--auto-terminate`
y `ActionOnFailure=TERMINATE_CLUSTER`, y espera. Tarda **10-20 min** (casi todo es arranque). El
cluster se apaga solo aunque cierren la terminal.

Resultado esperado: step `COMPLETED`, cluster `TERMINATED`, unas 6-12 horas normalizadas y
**24** particiones `month=`.

| Si falla… | Hagan esto |
|---|---|
| `The requested instance type m4.large is not supported` o error de versión | `EMR_RELEASE=emr-6.15.0 BUCKET=... bash aws/emr/run_emr_job.sh` |
| El step queda `FAILED` | Logs en S3: `emr-logs/<cluster-id>/steps/<step-id>/stderr.gz`. Normalmente es una ruta S3 mal escrita |
| `AccessDenied` en `create-cluster` | Las credenciales del Lab expiraron: vuelvan a pegar `~/.aws/credentials` |

## 6. Glue Data Catalog + Athena (R5, R6)

```bash
BUCKET=airline-wilches-garcia-24306 bash aws/athena/setup_athena.sh
```

Crea la base `airline_analytics` y las dos tablas con las columnas exactas del contrato
(`reservations_curated` con *partition projection* por `month`, sin crawler) y verifica:

- filas curadas = **1977131**
- filas de métricas = **288**
- bytes escaneados por una consulta de un mes ≈ **0,8 MB** (límite del harness ≈ 1,6 MB)

Abran `http://<IP>:3000/manager`, elijan una ruta y un mes (2023-01 a 2024-12): ahora el número viene de Athena (1-3 s).

## 7. Correr el harness (en la EC2)

```bash
BUCKET=airline-wilches-garcia-24306 bash aws/harness/run_harness.sh
```

La primera vez instala Python, Playwright y Chromium (≈ 3 min). Escribe la IP pública y el bucket en
`parcial2-harness/config.yaml` y deja `parcial2-harness/report.md`. **No lo corran mientras haya un
cluster EMR encendido** (R10 falla y R12 suma esas máquinas).

Guarden el reporte para la entrega (está en `.gitignore`, por eso se copia):

```bash
mkdir -p entrega && cp parcial2-harness/report.md parcial2-harness/report.json entrega/
```

y pásenlo al repo (desde la EC2 con `git add -f entrega/ && git commit && git push`, o copiando el
contenido desde el portátil). **Nunca suban `~/.aws/credentials` ni `.env`.**

Puntos que en el Learner Lab pueden salir *skipped / not verified* (falta de permisos para listar
algún servicio): anótenlos en el documento, como pide la sección 6 del enunciado.

## 8. Apagar al terminar la sesión

```bash
bash aws/estado_aws.sh    # EMR activos: vacío · EC2: solo airline-app · RDS / NAT / LB: vacío
```

Luego EC2 → seleccionar `airline-app` → **Instance state → Stop**. (El Lab también la detiene cuando se acaba
la sesión.) Los datos de PostgreSQL y S3 se conservan. **No borren** el bucket ni las tablas: el
profesor los necesita para su corrida.

Costo de lo que queda: EBS 20 GB ≈ US$ 1,6/mes; S3 < US$ 0,1/mes; la EC2 detenida no cobra cómputo.

## 9. Ventana de calificación del profesor

El profesor usa las URLs del `config.yaml` entregado y el sistema debe estar arriba en la ventana acordada:

1. Start Lab → EC2 → **Start** `airline-app` (los contenedores arrancan solos: `restart: unless-stopped`).
2. La IP pública **cambia** en cada arranque: actualicen `parcial2-harness/config.yaml` con la IP
   nueva (`IP=<nueva> BUCKET=... bash aws/harness/run_harness.sh` lo hace y además re-verifica) y súbanlo al repo.
3. Mantengan el Lab encendido durante la ventana (las sesiones duran 4 h).

Opcional: una **Elastic IP** asociada a la EC2 evita el cambio de IP. Mientras la instancia corre
cuesta lo mismo que la IP pública normal (US$ 0,005/h); detenida cuesta US$ 0,005/h (~US$ 3,6/mes
si se queda detenida todo el mes).

## 10. Si algo no responde

| Síntoma | Causa probable | Arreglo |
|---|---|---|
| El navegador no abre `:3000` | Security group sin el puerto | Añadir regla TCP 3000 / 8000 |
| `/manager` muestra error 503 | El backend no llega a Athena | `sudo docker compose logs api`; revisar hop limit y `ATHENA_OUTPUT` en `.env` |
| `/analytics/occupancy` da 404 en todo | Tablas no creadas o bucket distinto | Repetir paso 6 con el mismo `BUCKET` |
| R12 falla por diferencia | Hay más EC2 encendidas que la t3.small | Detener lo que sobre (`aws/estado_aws.sh`) |
| Tras reiniciar no responde | Docker no arrancó | `sudo systemctl start docker && sudo docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d` |
