#!/usr/bin/env bash
# Run on the server: bash deploy/linuxone/run_api.sh   (foreground; Ctrl+C stops it)
# uvicorn with safenet.env (shell variables win). SAFENET_WORKERS=auto = CPUs - 1.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
. deploy/linuxone/load_env.sh
load_env deploy/linuxone/safenet.env

if [ "${SAFENET_DEV_KEYS:-0}" = "1" ]; then echo "refusing: SAFENET_DEV_KEYS=1 on the server"; exit 1; fi
case "${SAFENET_DATABASE_URL:-}" in *CHANGE_ME*) echo "refusing: SAFENET_DATABASE_URL still says CHANGE_ME, run setup_postgres.sh"; exit 1 ;; esac

workers="${SAFENET_WORKERS:-auto}"
if [ "$workers" = "auto" ]; then workers=$(( $(nproc) - 1 )); [ "$workers" -lt 1 ] && workers=1; fi
export SAFENET_WORKERS="$workers"
mkdir -p logs
PY="${SAFENET_PYTHON:-$ROOT/.venv/bin/python}"
echo "SafeNet on $(uname -m), ${SAFENET_BIND:-127.0.0.1}:${SAFENET_PORT:-8000}, $workers workers"
exec "$PY" -m uvicorn safenet.api:app \
  --host "${SAFENET_BIND:-127.0.0.1}" --port "${SAFENET_PORT:-8000}" \
  --workers "$workers" --log-level "${SAFENET_LOG_LEVEL:-info}" \
  --no-server-header --timeout-keep-alive 30
