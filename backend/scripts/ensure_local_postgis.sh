#!/usr/bin/env bash
# Idempotent local PostGIS bootstrap: OS user, data dir, supervisor program, role, database, schema.
set -u
PG_BIN=/usr/lib/postgresql/15/bin
DATA=/var/lib/postgresql/15/main
CONF=/etc/postgresql/15/main/postgresql.conf
SQL="$(cd "$(dirname "$0")/.." && pwd)/sql/init.sql"
[ -x "$PG_BIN/postgres" ] || { echo "postgres binaries missing (install postgresql-15 postgresql-15-postgis-3)"; exit 1; }
id postgres >/dev/null 2>&1 || useradd -r -s /bin/bash -d /var/lib/postgresql postgres
mkdir -p /var/lib/postgresql /var/log/postgresql /var/run/postgresql
chown -R postgres /var/lib/postgresql /var/log/postgresql /var/run/postgresql
if [ ! -f "$DATA/PG_VERSION" ]; then
  su postgres -c "$PG_BIN/initdb -D $DATA -E UTF8 >/dev/null"
fi
if [ -f "$CONF" ]; then
  grep -q "^listen_addresses" "$CONF" || echo "listen_addresses = 'localhost'" >> "$CONF"
  CMD="$PG_BIN/postgres -D $DATA -c config_file=$CONF"
else
  CMD="$PG_BIN/postgres -D $DATA"
fi
SUP=/etc/supervisor/conf.d/postgres.conf
if [ ! -f "$SUP" ]; then
  printf '[program:postgres]\ncommand=%s\nuser=postgres\nautostart=true\nautorestart=true\nstderr_logfile=/var/log/supervisor/postgres.err.log\nstdout_logfile=/var/log/supervisor/postgres.out.log\n' "$CMD" > "$SUP"
  supervisorctl reread >/dev/null 2>&1; supervisorctl update >/dev/null 2>&1
fi
if ! su postgres -c "$PG_BIN/pg_isready -q -h localhost"; then
  supervisorctl start postgres >/dev/null 2>&1 || su postgres -c "$PG_BIN/pg_ctl -D $DATA -o '-c config_file=$CONF' -l /var/log/postgresql/bootstrap.log start >/dev/null"
fi
for _ in $(seq 1 30); do su postgres -c "$PG_BIN/pg_isready -q -h localhost" && break; sleep 1; done
su postgres -c "$PG_BIN/pg_isready -q -h localhost" || { echo "postgres did not become ready"; exit 1; }
su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='sar'\"" | grep -q 1 || su postgres -c "psql -qc \"CREATE USER sar WITH PASSWORD 'sar';\""
su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='sar_crop'\"" | grep -q 1 || su postgres -c "psql -qc 'CREATE DATABASE sar_crop OWNER sar;'"
su postgres -c "psql -qd sar_crop -c 'CREATE EXTENSION IF NOT EXISTS postgis;'"
su postgres -c "psql -qd sar_crop -c 'SET ROLE sar;' -f $SQL" >/dev/null
su postgres -c "psql -qd sar_crop -c 'GRANT ALL ON ALL TABLES IN SCHEMA public TO sar;'"
echo "local PostGIS ready"
