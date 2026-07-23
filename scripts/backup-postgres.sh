#!/usr/bin/env sh
set -eu

STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p backups
docker compose exec -T postgres pg_dump -U yuno -d yuno > "backups/yuno-${STAMP}.sql"
echo "Backup criado em backups/yuno-${STAMP}.sql"
