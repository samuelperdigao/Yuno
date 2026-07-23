#!/usr/bin/env sh
set -eu

if [ $# -ne 1 ]; then
  echo "Uso: ./scripts/restore-postgres.sh backups/yuno-YYYYMMDD-HHMMSS.sql"
  exit 1
fi

docker compose exec -T postgres psql -U yuno -d yuno < "$1"
echo "Restauracao concluida."
