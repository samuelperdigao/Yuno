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

if test "`$database_kind" = "sqlite"; then
  test -n "`$db_path"
  test -s "`$backup_path"
  rehearsal_path="$RemoteDir/backups/yuno-meta-v2-rehearsal-`$stamp.db"
  cp -- "`$backup_path" "`$rehearsal_path"
  DATABASE_URL="sqlite+aiosqlite:///`$rehearsal_path" .venv/bin/python -m alembic -c backend/alembic.ini upgrade head
  .venv/bin/python - "`$backup_path" "`$rehearsal_path" "`$db_path" <<'PY'
import sqlite3
import sys

protected = ("farm_tickets", "farm_ticket_entries", "farm_ticket_actions")

def count(connection, table):
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] if exists else 0

with sqlite3.connect(sys.argv[1]) as backup, sqlite3.connect(sys.argv[2]) as migrated:
    if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Restauracao ensaiada falhou no integrity_check")
    if migrated.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Copia migrada falhou no integrity_check")
    before = {table: count(backup, table) for table in protected}
    after = {table: count(migrated, table) for table in protected}
    if before != after:
        raise SystemExit(f"Contagens protegidas divergiram: {before} != {after}")
    head = migrated.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    if head != "c5d6e7f8a9b0":
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
    print(f"RESTORE_REHEARSAL_OK={sys.argv[2]}")
    print(f"MIGRATION_REHEARSAL_HEAD={head}")
    print(f"PROTECTED_COUNTS={after}")

print(f"RESTORE_COMMAND=cp -- '{sys.argv[1]}' '{sys.argv[3]}'")
PY
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose up -d --build
  sleep 10
  docker compose ps
  curl -fsS http://127.0.0.1:8000/health
  curl -fsSI http://127.0.0.1:5173/ >/dev/null
else
  echo "Docker nao encontrado; usando deploy systemd atual."
  .venv/bin/pip install -q -r backend/requirements.txt -r bot/requirements.txt
  sudo systemctl restart yuno-api.service yuno-bot.service

  api_ok=0
  for attempt in `$(seq 1 20); do
    if curl -fsS http://127.0.0.1:8000/health; then
      api_ok=1
      break
    fi
    sleep 2
  done

  test "`$api_ok" = "1"
  systemctl is-active yuno-api.service yuno-bot.service
fi

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
