#!/usr/bin/env bash
# "¿Qué está gastando dinero ahora mismo?"  Córralo antes de cerrar el Learner Lab y antes del harness.
#   bash aws/estado_aws.sh
REGION="${AWS_REGION:-us-east-1}"
set -u

echo "== EMR: clusters activos (debe estar vacío, R10) =="
aws emr list-clusters --region "$REGION" --active \
  --query 'Clusters[].{id:Id,nombre:Name,estado:Status.State}' --output table

echo "== EMR: horas normalizadas usadas en los últimos 45 días (tope R10: 150) =="
SINCE=$(date -u -d '45 days ago' +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -v-45d +%Y-%m-%dT%H:%M:%S)
TOTAL=0
for c in $(aws emr list-clusters --region "$REGION" --created-after "$SINCE" --query 'Clusters[].Id' --output text); do
  h=$(aws emr describe-cluster --region "$REGION" --cluster-id "$c" --query 'Cluster.NormalizedInstanceHours' --output text)
  TOTAL=$((TOTAL + h))
done
echo "   $TOTAL horas normalizadas"

echo "== EC2 encendidas (solo debe estar la t3.small) =="
aws ec2 describe-instances --region "$REGION" --filters Name=instance-state-name,Values=pending,running \
  --query 'Reservations[].Instances[].{id:InstanceId,tipo:InstanceType,ip:PublicIpAddress}' --output table

echo "== RDS (debe estar vacío: PostgreSQL vive en la EC2) =="
aws rds describe-db-instances --region "$REGION" \
  --query 'DBInstances[].{id:DBInstanceIdentifier,clase:DBInstanceClass,multiAZ:MultiAZ,estado:DBInstanceStatus}' --output table

echo "== NAT Gateways (debe estar vacío, R11) =="
aws ec2 describe-nat-gateways --region "$REGION" --filter Name=state,Values=pending,available \
  --query 'NatGateways[].NatGatewayId' --output table

echo "== Load balancers (debe estar vacío) =="
aws elbv2 describe-load-balancers --region "$REGION" --query 'LoadBalancers[].LoadBalancerName' --output table
