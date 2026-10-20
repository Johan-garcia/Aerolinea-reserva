#!/usr/bin/env bash
# Lanza el job PySpark en un cluster EMR efímero (R4) que se apaga solo al terminar (R10).
#
#   BUCKET=airline-wilches-garcia bash aws/emr/run_emr_job.sh
#
# Requisitos: AWS CLI con las credenciales del Learner Lab; data/raw/ generado con la semilla del equipo
#   (sudo docker compose --profile batch run --rm datagen).
# Instancias: 1 master + 2 core m4.large (el único tipo permitido en el Learner Lab, R11).
# Costo aproximado por corrida: 3 nodos x ~0,5 h x (0,10 EC2 + 0,03 EMR) ≈ US$ 0,20-0,40; ~6-12 h normalizadas.
set -euo pipefail

: "${BUCKET:?Defina BUCKET=nombre-del-bucket}"
REGION="${AWS_REGION:-us-east-1}"
RELEASE="${EMR_RELEASE:-emr-7.2.0}"     # si el Lab rechaza esta versión: EMR_RELEASE=emr-6.15.0
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

for f in flights.csv reservations.csv; do
  [ -s "$ROOT/data/raw/$f" ] || { echo "Falta data/raw/$f. Genere los datos primero (ver DESPLIEGUE_AWS.md, paso 4)."; exit 1; }
done
ROWS=$(($(wc -l < "$ROOT/data/raw/reservations.csv") - 1))
echo "reservations.csv tiene $ROWS filas (con 2.000.000 pedidas y semilla 24306 deben ser 2046430)."

ACTIVE=$(aws emr list-clusters --region "$REGION" --active --query 'length(Clusters)' --output text)
if [ "$ACTIVE" != "0" ]; then
  echo "Ya hay $ACTIVE cluster(s) EMR activo(s). Revise con: bash aws/estado_aws.sh"; exit 1
fi

echo "1/3 Subiendo datos crudos y el job a s3://$BUCKET ..."
aws s3 cp "$ROOT/data/raw/flights.csv"      "s3://$BUCKET/raw/flights.csv"      --region "$REGION"
aws s3 cp "$ROOT/data/raw/reservations.csv" "s3://$BUCKET/raw/reservations.csv" --region "$REGION"
aws s3 cp "$ROOT/spark/jobs/curate_reservations.py" "s3://$BUCKET/jobs/curate_reservations.py" --region "$REGION"

echo "2/3 Creando cluster EMR ($RELEASE) con --auto-terminate ..."
CLUSTER_ID=$(aws emr create-cluster \
  --region "$REGION" \
  --name "airline-curate-$(date +%Y%m%d-%H%M)" \
  --release-label "$RELEASE" \
  --applications Name=Spark \
  --instance-groups \
      InstanceGroupType=MASTER,InstanceCount=1,InstanceType=m4.large \
      InstanceGroupType=CORE,InstanceCount=2,InstanceType=m4.large \
  --service-role EMR_DefaultRole \
  --ec2-attributes InstanceProfile=EMR_EC2_DefaultRole \
  --log-uri "s3://$BUCKET/emr-logs/" \
  --auto-terminate \
  --steps "Type=Spark,Name=curate-reservations,ActionOnFailure=TERMINATE_CLUSTER,Args=[--deploy-mode,cluster,s3://$BUCKET/jobs/curate_reservations.py,--raw,s3://$BUCKET/raw,--curated,s3://$BUCKET/curated]" \
  --query ClusterId --output text)
echo "   Cluster: $CLUSTER_ID  (consola: EMR > Clusters)"

echo "3/3 Esperando a que termine (10-20 min; el cluster se apaga solo aunque cierre esta terminal) ..."
while true; do
  STATE=$(aws emr describe-cluster --cluster-id "$CLUSTER_ID" --region "$REGION" --query Cluster.Status.State --output text)
  echo "   $(date +%H:%M:%S) $STATE"
  case "$STATE" in TERMINATED|TERMINATED_WITH_ERRORS) break ;; esac
  sleep 60
done
aws emr list-steps --cluster-id "$CLUSTER_ID" --region "$REGION" \
  --query 'Steps[].{step:Name,state:Status.State}' --output table
aws emr describe-cluster --cluster-id "$CLUSTER_ID" --region "$REGION" \
  --query 'Cluster.{state:Status.State,reason:Status.StateChangeReason.Message,normalizedHours:NormalizedInstanceHours}' --output table

STEP_STATE=$(aws emr list-steps --cluster-id "$CLUSTER_ID" --region "$REGION" --query 'Steps[0].Status.State' --output text)
if [ "$STEP_STATE" = "COMPLETED" ]; then
  echo "OK. Particiones escritas:"
  aws s3 ls "s3://$BUCKET/curated/reservations_curated/" --region "$REGION" | grep -c "month=" || true
else
  echo "El step terminó en $STEP_STATE. Logs: s3://$BUCKET/emr-logs/$CLUSTER_ID/steps/"
  exit 1
fi
