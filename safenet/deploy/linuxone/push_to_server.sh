#!/usr/bin/env bash
# Run on your PC (Linux / macOS / WSL / Git Bash): copies the safenet folder to the server.
# Leaves out venvs, models, logs, keys and safenet.env, so nothing on the server that holds a
# secret or a trained model is overwritten.
#   SAFENET_SSH_KEY=/path/to/Key.pem bash deploy/linuxone/push_to_server.sh
set -euo pipefail
: "${SAFENET_SSH_KEY:?set SAFENET_SSH_KEY to the path of Key.pem}"
HOST="${SAFENET_HOST:-linux1@148.100.108.149}"
REMOTE_DIR="${SAFENET_REMOTE_DIR:-safenet}"      # relative to the server's home
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
SSH=(ssh -i "$SAFENET_SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

echo "copying $SRC -> $HOST:~/$REMOTE_DIR"
tar -C "$SRC" -czf - \
  --exclude='.venv' --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
  --exclude='models/*.joblib' --exclude='logs' --exclude='veri' --exclude='*.pem' \
  --exclude='config/api_keys.toml' --exclude='deploy/linuxone/safenet.env' --exclude='deploy/docker/.env' \
  --exclude='bench/results/*.json' --exclude='.git' \
  . | "${SSH[@]}" "$HOST" "mkdir -p ~/$REMOTE_DIR && tar -C ~/$REMOTE_DIR -xzf - && find ~/$REMOTE_DIR -name '*.sh' -exec chmod +x {} +"
echo "done. On the server: cd ~/$REMOTE_DIR && bash deploy/linuxone/setup_server.sh"
