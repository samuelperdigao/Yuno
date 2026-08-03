$ErrorActionPreference = "Stop"

$Branch = "main"
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

if (-not $SshKey) {
    throw "Chave SSH do Yuno nao encontrada nos caminhos conhecidos."
}

$dirty = git status --short
if ($dirty) {
    Write-Host $dirty
    throw "Existem alteracoes locais. Faca commit antes do deploy."
}

Write-Host "Enviando main para o GitHub..."
git push origin $Branch
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao enviar $Branch para o GitHub."
}

$remoteCommand = @"
set -euo pipefail
cd $RemoteDir

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && docker compose ps --status running postgres | grep -q postgres; then
  stamp=`$(date +%Y%m%d-%H%M%S)
  mkdir -p backups
  docker compose exec -T postgres pg_dump -U yuno -d yuno > "backups/yuno-predeploy-`$stamp.sql"
  test -s "backups/yuno-predeploy-`$stamp.sql"
  echo "Backup pre-deploy criado: backups/yuno-predeploy-`$stamp.sql"
elif test -f .env; then
  db_url=`$(grep -m1 '^DATABASE_URL=' .env | cut -d= -f2- || true)
  case "`$db_url" in
    sqlite+aiosqlite:///*|sqlite:///*)
      db_path="`${db_url#*///}"
      case "`$db_path" in
        /*) ;;
        *) db_path="$RemoteDir/`$db_path" ;;
      esac
      if test -f "`$db_path"; then
        stamp=`$(date +%Y%m%d-%H%M%S)
        backup_path="$RemoteDir/backups/yuno-predeploy-`$stamp.db"
        mkdir -p "$RemoteDir/backups"
        .venv/bin/python - "`$db_path" "`$backup_path" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    source.backup(target)
PY
        test -s "`$backup_path"
        echo "Backup pre-deploy criado: `$backup_path"
      fi
      ;;
  esac
fi

GIT_SSH_COMMAND='ssh -i $DeployKey -o StrictHostKeyChecking=accept-new' git pull --ff-only origin $Branch

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
Write-Host "Deploy concluido."
