#!/usr/bin/env bash
# Lanza el job PySpark en un cluster EMR efímero (R4) que se apaga solo al terminar (R10).
#
#   BUCKET=mi-bucket ./aws/emr/run_emr_job.sh
#
# Requisitos: AWS CLI con las credenciales del Learner Lab; data/raw/ generado con la semilla del equipo.
# Instancias: 1 master + 2 core m4.large (el único tipo permitido en el Learner Lab, R11).
set -euo pipefail

: "${BUCKET:?Defina BUCKET=nombre-del-bucket}"
REGION="${AWS_REGION:-us-east-1}"
RELEASE="${EMR_RELEASE:-emr-7.2.0}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "1/3 Subiendo datos crudos y el job a s3://$BUCKET ..."
aws s3 cp "$ROOT/data/raw/flights.csv"      "s3://$BUCKET/raw/flights.csv"      --region "$REGION"
aws s3 cp "$ROOT/data/raw/reservations.csv" "s3://$BUCKET/raw/reservations.csv" --region "$REGION"
aws s3 cp "$ROOT/spark/jobs/curate_reservations.py" "s3://$BUCKET/jobs/curate_reservations.py" --region "$REGION"

echo "2/3 Creando cluster EMR con --auto-terminate ..."
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
echo "   Cluster: $CLUSTER_ID"

echo "3/3 Esperando a que termine (el cluster se apaga solo) ..."
aws emr wait cluster-terminated --cluster-id "$CLUSTER_ID" --region "$REGION"
aws emr list-steps --cluster-id "$CLUSTER_ID" --region "$REGION" \
  --query 'Steps[].{step:Name,state:Status.State}' --output table
aws emr describe-cluster --cluster-id "$CLUSTER_ID" --region "$REGION" \
  --query 'Cluster.{state:Status.State,reason:Status.StateChangeReason.Message,normalizedHours:NormalizedInstanceHours}' --output table
