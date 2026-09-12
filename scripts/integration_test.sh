#!/usr/bin/env bash
set -euo pipefail

rm -rf artifacts/integration
export STATE_FILE="artifacts/integration/test-state.json"
export ARTIFACTS_DIR="artifacts/integration"
unset TELEGRAM_TOKEN TELEGRAM_CHAT_ID

set +e
python tracker.py
status=$?
set -e

if [ "$status" -eq 0 ]; then
  echo 'Prueba de integración: lectura de precio completada.'
elif [ -f artifacts/integration/failure.png ] && [ -f artifacts/integration/failure.txt ]; then
  echo 'Prueba de integración: error/CAPTCHA capturado con evidencia visual.'
else
  echo "El monitor falló sin generar los diagnósticos esperados (estado $status)." >&2
  exit "$status"
fi
