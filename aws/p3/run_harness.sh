#!/usr/bin/env bash
# Corre el harness oficial del Parcial 3 contra el despliegue en AWS y deja report.md / report.json.
#
#   BUCKET=airline-wilches-garcia-24306 bash aws/p3/run_harness.sh                 # IP pública de esta máquina
#   BUCKET=airline-wilches-garcia-24306 IP=3.85.10.20 bash aws/p3/run_harness.sh
#
# Requisitos: stream creado (aws/p3/stream.sh create), contenedores arriba, ref/ generado.
# Usa las credenciales normales de AWS (rol de la instancia o ~/.aws); nunca las suba a git.
set -euo pipefail
: "${BUCKET:?Defina BUCKET=nombre-del-bucket}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
H="$ROOT/parcial3-harness-estudiantes"
IP="${IP:-$(curl -fsS https://checkip.amazonaws.com)}"

echo "Configurando $H/config.yaml con IP=$IP y BUCKET=$BUCKET"
sed -i.bak -E \
  -e "s#base_url: \"http://[^:\"]+:8000\"#base_url: \"http://${IP}:8000\"#" \
  -e "s#s3://[^/\"]+/raw/events/#s3://${BUCKET}/raw/events/#" \
  -e "s#s3://[^/\"]+/athena-results/#s3://${BUCKET}/athena-results/#" \
  "$H/config.yaml" && rm -f "$H/config.yaml.bak"
grep -E "seed|base_url|kinesis_stream|raw_events_uri|athena_" "$H/config.yaml"

if [ ! -x "$ROOT/.venv-harness3/bin/pytest" ]; then
  echo "Instalando dependencias del harness (solo la primera vez)..."
  python3 -m venv --help >/dev/null 2>&1 && python3 -c "import ensurepip" 2>/dev/null \
    || { sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv python3-pip >/dev/null; }
  python3 -m venv "$ROOT/.venv-harness3"
  "$ROOT/.venv-harness3/bin/pip" install -q -r "$H/requirements.txt"
fi

cd "$H"
"$ROOT/.venv-harness3/bin/pytest" -q -p no:warnings || true
echo
echo "Reporte: $H/report.md"
sed -n '1,20p' "$H/report.md"
mkdir -p "$ROOT/entrega/parcial3"
cp "$H/report.md" "$H/report.json" "$ROOT/entrega/parcial3/"
echo "Copiado a entrega/parcial3/ (súbalo al repo: git add -f entrega/parcial3)"
