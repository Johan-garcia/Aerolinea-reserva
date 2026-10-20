#!/usr/bin/env bash
# Prepara la EC2 (Ubuntu 24.04, t3.small) y levanta db + api + frontend con Athena como motor analítico.
#
#   BUCKET=airline-wilches-garcia bash aws/ec2/bootstrap.sh
#
# Se puede correr varias veces: solo instala lo que falta y vuelve a levantar los contenedores.
# El backend usa el rol de la instancia (LabInstanceProfile) para Athena: no hay credenciales en archivos.
set -euo pipefail

: "${BUCKET:?Defina BUCKET=nombre-del-bucket (el mismo de S3/Athena)}"
TEAM_SEED="${TEAM_SEED:-24306}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "1/5 Swap de 1 GB (la t3.small tiene 2 GB de RAM; evita que el build se quede sin memoria)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "2/5 Docker + plugin compose"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi
sudo systemctl enable --now docker >/dev/null

echo "3/5 AWS CLI"
command -v aws >/dev/null || sudo snap install aws-cli --classic

echo "4/5 Archivo .env (no se sube a git)"
cat > .env <<EOF
TEAM_SEED=${TEAM_SEED}
ATHENA_OUTPUT=s3://${BUCKET}/athena-results/
ATHENA_DATABASE=airline_analytics
ATHENA_WORKGROUP=primary
AWS_REGION=us-east-1
UVICORN_WORKERS=2
EOF

echo "5/5 Construyendo y levantando contenedores (la primera vez tarda 3-5 min)"
sudo docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build

echo "Esperando a que el backend responda..."
for _ in $(seq 1 60); do
  curl -fsS http://localhost:8000/health >/dev/null 2>&1 && break
  sleep 3
done
curl -fsS http://localhost:8000/health && echo
curl -fsS -o /dev/null -w "frontend: HTTP %{http_code}\n" http://localhost:3000/

echo "Comprobando que el contenedor del backend obtiene credenciales del rol de la instancia..."
if sudo docker compose exec -T api python -c "import boto3; print('rol:', boto3.client('sts').get_caller_identity()['Arn'])"; then
  echo "OK: el backend puede llamar a Athena."
else
  cat <<'MSG'
ERROR: el contenedor no obtiene credenciales.
  1) Revise que la instancia tenga el perfil IAM LabInstanceProfile (Acciones > Seguridad > Modificar rol de IAM).
  2) Suba el "hop limit" de metadatos a 2 (los contenedores están a un salto más):
     aws ec2 modify-instance-metadata-options --instance-id <ID> --http-put-response-hop-limit 2 --http-endpoint enabled
  Luego: sudo docker compose -f docker-compose.yml -f docker-compose.aws.yml restart api
MSG
  exit 1
fi

IP="$(curl -fsS https://checkip.amazonaws.com || echo '<IP-PUBLICA>')"
echo
echo "Listo:"
echo "  Clientes:  http://${IP}:3000/"
echo "  Gerencia:  http://${IP}:3000/manager"
echo "  API:       http://${IP}:8000/docs"
