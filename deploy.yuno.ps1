param(
    [Parameter(Mandatory = $false)]
    [string]$Ref = "main",
    [Parameter(Mandatory = $false)]
    [string]$ExpectedSha = "",
    [ValidateSet("test")]
    [string]$Environment = "test"
)

$ErrorActionPreference = "Stop"

$Remote = "ubuntu@163.176.143.142"
$UserProfileDir = [Environment]::GetFolderPath("UserProfile")
$SshKeyCandidates = @(
    (Join-Path $PSScriptRoot "..\Morro do Mineiro Bot\oracle.key"),
    (Join-Path $UserProfileDir ".ssh\yuno_oracle_ed25519"),
    (Join-Path $PSScriptRoot "..\Bot Discord\oracle.key")
)
$SshKey = $SshKeyCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$RemoteDir = "/home/ubuntu/yuno"
$DeployKey = "/home/ubuntu/.ssh/yuno_github_deploy_ed25519"

Write-Host "== Yuno deploy =="
Write-Host "Ambiente: $Environment"

if (-not $SshKey) {
    throw "Chave SSH do Yuno nao encontrada nos caminhos conhecidos."
}

$dirty = git status --short
if ($dirty) {
    Write-Host $dirty
    throw "Existem alteracoes locais. Faca commit antes do deploy."
}

$ResolvedSha = (git rev-parse "$Ref^{commit}").Trim()
if (-not $ResolvedSha -or $LASTEXITCODE -ne 0) {
    throw "Nao foi possivel resolver o ref Git '$Ref'."
}
if ($ExpectedSha -and $ResolvedSha -ne $ExpectedSha) {
    throw "O ref $Ref aponta para $ResolvedSha, diferente do SHA esperado $ExpectedSha."
}

$CurrentBranch = (git branch --show-current).Trim()
if ($CurrentBranch -and $Ref -eq $CurrentBranch) {
    Write-Host "Enviando $CurrentBranch para o GitHub..."
    git push origin $CurrentBranch
} else {
    Write-Host "Validando que o SHA $ResolvedSha esta disponivel no remoto..."
    git fetch origin --quiet
    git branch -r --contains $ResolvedSha | Out-Null
}
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao publicar ou localizar $ResolvedSha no GitHub."
}
Write-Host "SHA aprovado para deploy: $ResolvedSha"

$remoteCommand = @"
set -euo pipefail
cd $RemoteDir
database_kind=""
db_path=""
db_url=""
pg_url=""
backup_path=""
stamp=`$(date +%Y%m%d-%H%M%S)

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && docker compose ps --status running postgres | grep -q postgres; then
  database_kind="postgresql"
  mkdir -p backups
  backup_path="$RemoteDir/backups/yuno-predeploy-`$stamp.sql"
  docker compose exec -T postgres pg_dump -U yuno -d yuno > "`$backup_path"
  test -s "`$backup_path"
  echo "Backup pre-deploy criado: `$backup_path"
elif test -f .env; then
  db_url=`$(grep -m1 '^DATABASE_URL=' .env | cut -d= -f2- || true)
  case "`$db_url" in
    postgresql+asyncpg://*)
      database_kind="postgresql-host"
      pg_url="postgresql://`${db_url#postgresql+asyncpg://}"
      mkdir -p backups
      backup_path="$RemoteDir/backups/yuno-predeploy-`$stamp.sql"
      pg_dump "`$pg_url" > "`$backup_path"
      test -s "`$backup_path"
      echo "Backup PostgreSQL pre-deploy criado: `$backup_path"
      ;;
    sqlite+aiosqlite:///*|sqlite:///*)
      database_kind="sqlite"
      db_path="`${db_url#*///}"
      case "`$db_path" in
        /*) ;;
        *) db_path="$RemoteDir/`$db_path" ;;
      esac
      if test -f "`$db_path"; then
        backup_path="$RemoteDir/backups/yuno-predeploy-`$stamp.db"
        mkdir -p "$RemoteDir/backups"
        .venv/bin/python - "`$db_path" "`$backup_path" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    source.backup(target)
    if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Banco de origem falhou no integrity_check")
    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Backup falhou no integrity_check")
PY
        test -s "`$backup_path"
        echo "Backup pre-deploy criado: `$backup_path"
      fi
      ;;
  esac
fi

test -z "`$(git status --porcelain)"
GIT_SSH_COMMAND='ssh -i $DeployKey -o StrictHostKeyChecking=accept-new' git fetch origin --prune
git cat-file -e '$ResolvedSha^{commit}'
git checkout --detach '$ResolvedSha'
test "`$(git rev-parse HEAD)" = '$ResolvedSha'

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  .venv/bin/pip install -q -r backend/requirements.txt -r bot/requirements.txt
fi

if test "`$database_kind" = "sqlite"; then
  test -n "`$db_path"
  test -s "`$backup_path"
  rehearsal_path="$RemoteDir/backups/yuno-meta-v2-rehearsal-`$stamp.db"
  cp -- "`$backup_path" "`$rehearsal_path"
  DATABASE_URL="sqlite+aiosqlite:///`$rehearsal_path" .venv/bin/python -m alembic -c backend/alembic.ini upgrade head
  .venv/bin/python - "`$backup_path" "`$rehearsal_path" "`$db_path" <<'PY'
import sqlite3
import sys

protected = (
    "farm_ticket_v2_tickets",
    "farm_ticket_v2_entries",
    "farm_ticket_v2_proofs",
    "farm_ticket_v2_allocations",
)

def count(connection, table):
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] if exists else 0

def exists(connection, table):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None

with sqlite3.connect(sys.argv[1]) as backup, sqlite3.connect(sys.argv[2]) as migrated:
    if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Restauracao ensaiada falhou no integrity_check")
    if migrated.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Copia migrada falhou no integrity_check")
    before = {table: count(backup, table) for table in protected}
    after = {table: count(migrated, table) for table in protected}
    legacy_present_before = exists(backup, "farm_tickets")
    configs_present_before = exists(backup, "farm_ticket_configs")
    legacy_before = count(backup, "farm_tickets")
    configs_before = count(backup, "farm_ticket_configs")
    if before != after:
        raise SystemExit(f"Contagens protegidas divergiram: {before} != {after}")
    head = migrated.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    if head != "f8a9b0c1d2e3":
        raise SystemExit(f"Head inesperado na copia migrada: {head}")
    legacy = migrated.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='farm_weekly_goals'"
    ).fetchone()
    if legacy:
        raise SystemExit("farm_weekly_goals permaneceu na copia migrada")
    meta_tables = migrated.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'meta_%'"
    ).fetchone()[0]
    if meta_tables != 11:
        raise SystemExit(f"Quantidade inesperada de tabelas Meta: {meta_tables}")
    ticket_v2_tables = migrated.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'farm_ticket_v2_%'"
    ).fetchone()[0]
    if ticket_v2_tables != 18:
        raise SystemExit(f"Quantidade inesperada de tabelas Tickets V2: {ticket_v2_tables}")
    if count(migrated, "farm_tickets") or count(migrated, "farm_ticket_configs"):
        raise SystemExit("Tabelas legadas de tickets permaneceram apos o cutover")
    archive_count = migrated.execute(
        "SELECT count(*) FROM farm_ticket_v2_legacy_archive "
        "WHERE source_namespace='yuno.legacy.farm_tickets.cutover'"
    ).fetchone()[0]
    config_archive_count = migrated.execute(
        "SELECT count(*) FROM farm_ticket_v2_legacy_archive "
        "WHERE source_namespace='yuno.legacy.farm_ticket_configs'"
    ).fetchone()[0]
    if (
        (legacy_present_before and archive_count != legacy_before)
        or (configs_present_before and config_archive_count != configs_before)
    ):
        raise SystemExit(
            "Arquivo legado divergente: "
            f"tickets={legacy_before}/{archive_count}, "
            f"configs={configs_before}/{config_archive_count}"
        )
    print(f"RESTORE_REHEARSAL_OK={sys.argv[2]}")
    print(f"MIGRATION_REHEARSAL_HEAD={head}")
    print(f"PROTECTED_COUNTS={after}")

print(f"RESTORE_COMMAND=cp -- '{sys.argv[1]}' '{sys.argv[3]}'")
PY
fi

if test "`$database_kind" = "postgresql-host"; then
  test -s "`$backup_path"
  rehearsal_db="yuno_rehearsal_`$(date +%Y%m%d%H%M%S)"
  db_owner=`$(.venv/bin/python - "`$db_url" <<'PY'
import sys
from urllib.parse import urlsplit
print(urlsplit(sys.argv[1].replace("postgresql+asyncpg://", "postgresql://", 1)).username or "")
PY
  )
  test -n "`$db_owner"
  cleanup_rehearsal() {
    sudo -u postgres dropdb --if-exists "`$rehearsal_db" >/dev/null 2>&1 || true
  }
  trap cleanup_rehearsal EXIT
  cleanup_rehearsal
  sudo -u postgres createdb -O "`$db_owner" "`$rehearsal_db"
  sudo -u postgres psql -v ON_ERROR_STOP=1 -d "`$rehearsal_db" < "`$backup_path" >/dev/null
  rehearsal_url=`$(.venv/bin/python - "`$db_url" "`$rehearsal_db" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
value = urlsplit(sys.argv[1])
print(urlunsplit((value.scheme, value.netloc, "/" + sys.argv[2], value.query, value.fragment)))
PY
  )
  legacy_present=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select to_regclass('public.farm_tickets') is not null")
  config_present=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select to_regclass('public.farm_ticket_configs') is not null")
  legacy_count=0
  config_count=0
  if test "`$legacy_present" = "t"; then
    legacy_count=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_tickets")
  fi
  if test "`$config_present" = "t"; then
    config_count=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_ticket_configs")
  fi
  v2_ticket_count=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_ticket_v2_tickets")
  v2_event_count=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_ticket_v2_events")
  DATABASE_URL="`$rehearsal_url" .venv/bin/python -m alembic -c backend/alembic.ini upgrade head
  rehearsal_head=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c 'select version_num from alembic_version')
  test "`$rehearsal_head" = "f8a9b0c1d2e3"
  test "`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select to_regclass('public.farm_tickets') is null")" = "t"
  test "`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select to_regclass('public.farm_cycles') is null")" = "t"
  archive_count=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_ticket_v2_legacy_archive where source_namespace='yuno.legacy.farm_tickets.cutover'")
  config_archive_count=`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_ticket_v2_legacy_archive where source_namespace='yuno.legacy.farm_ticket_configs'")
  if test "`$legacy_present" = "t"; then test "`$legacy_count" = "`$archive_count"; fi
  if test "`$config_present" = "t"; then test "`$config_count" = "`$config_archive_count"; fi
  test "`$v2_ticket_count" = "`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_ticket_v2_tickets")"
  test "`$v2_event_count" = "`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_ticket_v2_events")"
  test "`$(sudo -u postgres psql -At -d "`$rehearsal_db" -c "select count(*) from farm_ticket_v2_legacy_archive where length(checksum_sha256) <> 64")" = "0"
  echo "POSTGRES_RESTORE_REHEARSAL_OK=`$rehearsal_db"
  echo "POSTGRES_MIGRATION_REHEARSAL_HEAD=`$rehearsal_head"
  cleanup_rehearsal
  trap - EXIT
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose up -d postgres redis minio minio-init
  docker compose build api bot dashboard
  docker compose run --rm api python -m alembic -c alembic.ini upgrade head
  docker compose up -d
  sleep 10
  docker compose ps
  curl -fsS http://127.0.0.1:8000/health
  curl -fsSI http://127.0.0.1:5173/ >/dev/null
else
  echo "Docker nao encontrado; usando deploy systemd atual."
  .venv/bin/python -m alembic -c backend/alembic.ini upgrade head
  sudo systemctl stop yuno-bot.service
  sudo systemctl restart yuno-api.service

  api_ok=0
  for attempt in `$(seq 1 20); do
    if curl -fsS http://127.0.0.1:8000/health; then
      api_ok=1
      break
    fi
    sleep 2
  done

  test "`$api_ok" = "1"
  sudo systemctl restart yuno-bot.service
  bot_ok=0
  for attempt in `$(seq 1 20); do
    if systemctl is-active --quiet yuno-bot.service; then
      bot_ok=1
      break
    fi
    sleep 1
  done
  test "`$bot_ok" = "1"
  systemctl is-active yuno-api.service yuno-bot.service
fi

if grep -q '^OBJECT_STORAGE_ENDPOINT=..*' .env 2>/dev/null; then
  storage_endpoint=`$(grep -m1 '^OBJECT_STORAGE_ENDPOINT=' .env | cut -d= -f2-)
  curl -fsS "`${storage_endpoint%/}/minio/health/live" >/dev/null
  echo "OBJECT_STORAGE_HEALTH=ok"
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  actual_head=`$(docker compose run --rm api python -m alembic -c alembic.ini current | tail -n 1 | awk '{print `$1}')
else
  actual_head=`$(.venv/bin/python -m alembic -c backend/alembic.ini current | tail -n 1 | awk '{print `$1}')
fi
test "`$actual_head" = "f8a9b0c1d2e3"
echo "ALEMBIC_HEAD=`$actual_head"

echo "DEPLOYED_SHA=`$(git rev-parse HEAD)"
"@

Write-Host "Atualizando servidor Oracle..."
$remoteScript = $remoteCommand -replace "`r", ""
$localScript = [System.IO.Path]::GetTempFileName()
$remoteScriptPath = "/tmp/yuno-deploy-$([Guid]::NewGuid().ToString("N")).sh"

try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($localScript, $remoteScript, $utf8NoBom)

    scp -i $SshKey -o StrictHostKeyChecking=accept-new $localScript "${Remote}:$remoteScriptPath"
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao enviar script temporario para o servidor Oracle."
    }

    ssh -i $SshKey -o StrictHostKeyChecking=accept-new $Remote "bash $remoteScriptPath; status=`$?; rm -f $remoteScriptPath; exit `$status"
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao atualizar o servidor Oracle."
    }
}
finally {
    if (Test-Path $localScript) {
        Remove-Item -LiteralPath $localScript -Force
    }
}

Write-Host ""
Write-Host "Deploy de teste concluido no SHA $ResolvedSha."
