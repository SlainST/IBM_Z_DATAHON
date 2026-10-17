#!/usr/bin/env bash
# Run on the server: bash deploy/linuxone/setup_postgres.sh
# Creates the safenet role and UTF8 database with a random password, sets timeouts, and writes
# SAFENET_DATABASE_URL into safenet.env (chmod 600). The password goes to psql through stdin,
# never on a command line. Safe to re-run: it rotates the password.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV="$ROOT/deploy/linuxone/safenet.env"
DB="${SAFENET_DB_NAME:-safenet}"
ROLE="${SAFENET_DB_USER:-safenet}"

command -v psql >/dev/null || { echo "Postgres missing: sudo apt install postgresql (ask the team first)"; exit 1; }
systemctl is-active --quiet postgresql || { echo "postgresql service not running: sudo systemctl enable --now postgresql"; exit 1; }
[ -f "$ENV" ] || { echo "run setup_server.sh first"; exit 1; }

PW="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
sudo -u postgres psql -v ON_ERROR_STOP=1 -q -d postgres <<SQL
SELECT 'CREATE ROLE $ROLE LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$ROLE')\gexec
ALTER ROLE $ROLE WITH LOGIN PASSWORD '$PW';
SELECT 'CREATE DATABASE $DB OWNER $ROLE ENCODING ''UTF8'' TEMPLATE template0' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB')\gexec
ALTER ROLE $ROLE SET statement_timeout = '2s';
ALTER ROLE $ROLE SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE $ROLE SET lock_timeout = '1s';
SQL
sudo -u postgres psql -q -d "$DB" -c "GRANT ALL ON SCHEMA public TO $ROLE;" >/dev/null

URL="postgresql://$ROLE:$PW@127.0.0.1:5432/$DB"
tmp="$(mktemp)"; chmod 600 "$tmp"
grep -v -E '^\s*#?\s*SAFENET_DATABASE_URL=' "$ENV" > "$tmp" || true
echo "SAFENET_DATABASE_URL=$URL" >> "$tmp"
mv "$tmp" "$ENV"; chmod 600 "$ENV"

if PGPASSWORD="$PW" psql -h 127.0.0.1 -U "$ROLE" -d "$DB" -Atqc 'select 1' >/dev/null 2>&1; then
  echo "postgres ok: $ROLE@127.0.0.1/$DB, URL written to deploy/linuxone/safenet.env"
else
  echo "role created but password login on 127.0.0.1 failed."
  echo "pg_hba.conf must use scram-sha-256 (not ident/peer) for 'host all all 127.0.0.1/32'; then: sudo systemctl reload postgresql"
  exit 1
fi
