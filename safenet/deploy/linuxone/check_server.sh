#!/usr/bin/env bash
# What machine is this? Read-only: changes nothing. Run on the server: bash deploy/linuxone/check_server.sh
set -u
row() { printf '%-14s %s\n' "$1" "$2"; }
have() { command -v "$1" >/dev/null 2>&1; }

row arch "$(uname -m)"
mt=$(grep -m1 -o 'machine = [0-9A-Z]*' /proc/cpuinfo 2>/dev/null | awk '{print $3}')
case "$mt" in
  3931|3932) gen="z16 / LinuxONE 4" ;;
  9175|9176) gen="z17 / LinuxONE 5" ;;
  8561|8562) gen="z15 / LinuxONE III" ;;
  "") gen="not IBM Z" ;;
  *) gen="IBM Z" ;;
esac
row machine_type "${mt:-?} ($gen)"
if grep -qw nnpa /proc/cpuinfo 2>/dev/null; then row nnpa "yes (Telum AI accelerator)"; else row nnpa "no"; fi
row cpus "$(nproc)"
row ram "$(free -h | awk '/^Mem:/{print $2" total, "$7" available"}')"
row disk "$(df -h "$HOME" | awk 'NR==2{print $4" free in $HOME"}')"
row os "$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-?}")"
row kernel "$(uname -r)"
for py in python3 python3.12 python3.11; do have "$py" && row "$py" "$($py --version 2>&1)"; done
if have psql; then row postgres "$(psql --version)"; else row postgres "not installed"; fi
row pg_service "$(systemctl is-active postgresql 2>/dev/null; true)"
if ldconfig -p 2>/dev/null | grep -q 'libpq.so.5'; then row libpq5 "yes"; else row libpq5 "no (apt install libpq5)"; fi
for tool in docker podman nginx; do have "$tool" && row "$tool" "$($tool --version 2>&1 | head -1)"; done
row linger "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo ?)"

echo
echo "OS Python libraries (venv uses --system-site-packages):"
python3 - <<'PY'
import importlib
for name in ["numpy", "scipy", "sklearn", "joblib", "pandas", "fastapi", "uvicorn", "psycopg"]:
    try:
        m = importlib.import_module(name)
        print(f"  {name:10} {getattr(m, '__version__', 'ok')}")
    except Exception:
        print(f"  {name:10} missing")
PY

echo
echo "Listening ports:"
(ss -ltnH 2>/dev/null || netstat -ltn 2>/dev/null) | awk '{print "  "$4}' | sort -u
echo
echo "Load: $(cut -d' ' -f1-3 /proc/loadavg)"
