#!/usr/bin/env bash
# Run on your PC: localhost:8000 -> the API on the server (which listens on 127.0.0.1 only).
#   SAFENET_SSH_KEY=/path/to/Key.pem bash deploy/linuxone/tunnel.sh
# PowerShell: ssh -i C:\path\Key.pem -N -L 8000:127.0.0.1:8000 linux1@148.100.108.149
set -euo pipefail
: "${SAFENET_SSH_KEY:?set SAFENET_SSH_KEY to the path of Key.pem}"
HOST="${SAFENET_HOST:-linux1@148.100.108.149}"
LOCAL_PORT="${SAFENET_LOCAL_PORT:-8000}"
echo "http://localhost:$LOCAL_PORT -> $HOST:127.0.0.1:8000  (Ctrl+C closes)"
exec ssh -i "$SAFENET_SSH_KEY" -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L "$LOCAL_PORT:127.0.0.1:8000" "$HOST"
