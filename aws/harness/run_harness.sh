#!/usr/bin/env bash
# Corre el harness oficial contra el despliegue en AWS y deja report.md / report.json.
#
#   BUCKET=airline-wilches-garcia bash aws/harness/run_harness.sh            # IP pública de esta máquina
#   BUCKET=airline-wilches-garcia IP=3.85.10.20 bash aws/harness/run_harness.sh
#
# Usa las credenciales del Learner Lab de ~/.aws/credentials (nunca las suba a git).
# No lo corra con un cluster EMR encendido: R10 fallaría y R12 sumaría esas máquinas.
set -euo pipefail

: "${BUCKET:?Defina BUCKET=nombre-del-bucket}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
H="$ROOT/parcial2-harness"
IP="${IP:-$(curl -fsS https://checkip.amazonaws.com)}"

echo "Configurando parcial2-harness/config.yaml con IP=$IP y BUCKET=$BUCKET"
sed -i -E \
  -e "s#base_url: \"http://[^:\"]+:8000\"#base_url: \"http://${IP}:8000\"#" \
  -e "s#base_url: \"http://[^:\"]+:3000\"#base_url: \"http://${IP}:3000\"#" \
  -e "s#athena_output: \"s3://[^/\"]+/athena-results/\"#athena_output: \"s3://${BUCKET}/athena-results/\"#" \
  "$H/config.yaml"
grep -E "base_url|athena_output|seed" "$H/config.yaml"

if [ ! -x "$ROOT/.venv-harness/bin/pytest" ]; then
  echo "Instalando dependencias del harness (solo la primera vez)..."
  sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv python3-pip >/dev/null
  python3 -m venv "$ROOT/.venv-harness"
  "$ROOT/.venv-harness/bin/pip" install -q -r "$H/requirements.txt"
  sudo "$ROOT/.venv-harness/bin/playwright" install-deps chromium
  "$ROOT/.venv-harness/bin/playwright" install chromium
fi

cd "$H"
"$ROOT/.venv-harness/bin/pytest" -q || true
echo
echo "Reporte: $H/report.md"
sed -n '1,20p' "$H/report.md"
