#!/usr/bin/env bash
# Run on the server from the safenet folder: bash deploy/linuxone/setup_server.sh
# venv (--system-site-packages) + requirements/server.txt + models/ logs/ config/ + safenet.env.
# Uses no sudo: if OS packages are missing it prints the apt line and stops.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

missing=()
python3 -c 'import numpy, scipy, sklearn, joblib' 2>/dev/null || missing+=(python3-numpy python3-scipy python3-sklearn python3-joblib)
python3 -c 'import ensurepip' 2>/dev/null || missing+=(python3-venv)
if [ ${#missing[@]} -gt 0 ]; then
  if [ -f /etc/debian_version ]; then
    echo "Missing OS packages. Run once (ask the team first, it uses sudo):"
    echo "  sudo apt install ${missing[*]}"
  else
    echo "Missing: ${missing[*]}. On RHEL/SLES install python3-numpy python3-scipy python3-scikit-learn python3-joblib libpq (see SAFENET_ARCHITECTURE.md, section 6)."
  fi
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv --system-site-packages .venv
fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements/server.txt
.venv/bin/python -c 'import numpy, sklearn, fastapi, uvicorn; print("python libs ok: numpy", numpy.__version__, "sklearn", sklearn.__version__)'
if ldconfig -p | grep -q 'libpq.so.5'; then
  .venv/bin/python -m pip install -q -r requirements/postgres.txt
  .venv/bin/python -c 'import psycopg; print("psycopg", psycopg.__version__, "libpq", psycopg.pq.version())'
else
  echo "note: libpq5 missing, Postgres driver skipped (sudo apt install libpq5 postgresql, then re-run)"
fi

mkdir -p models logs config
ENV=deploy/linuxone/safenet.env
if [ ! -f "$ENV" ]; then
  cp deploy/linuxone/safenet.env.example "$ENV"
  echo "created $ENV"
fi
chmod 600 "$ENV"
[ -f config/api_keys.toml ] && chmod 600 config/api_keys.toml

settings=""
for f in config/ayarlar.toml ayarlar.toml; do [ -f "$f" ] && { settings="$f"; break; }; done
if [ -n "$settings" ]; then
  .venv/bin/python -c "import tomllib,sys; d=tomllib.load(open(sys.argv[1],'rb')); print('$settings ok, platforms:', ', '.join(sorted(d.get('platform',{}))))" "$settings"
else
  echo "warning: no ayarlar.toml found (config/ayarlar.toml)"
fi

if grep -Eq '^\s*SAFENET_DEV_KEYS\s*=\s*1' "$ENV"; then
  echo "ERROR: SAFENET_DEV_KEYS=1 in $ENV. Never on the server."; exit 1
fi
echo "setup done. Next: bash deploy/linuxone/setup_postgres.sh, then bash deploy/linuxone/run_api.sh"
