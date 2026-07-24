$ErrorActionPreference = "Stop"

$Branch = "main"
$Remote = "ubuntu@163.176.143.142"
$SshKey = "C:\Projetos\Bot Discord\oracle.key"
$RemoteDir = "/home/ubuntu/yuno"
$DeployKey = "/home/ubuntu/.ssh/yuno_github_deploy_ed25519"

Write-Host "== Yuno deploy =="

if (-not (Test-Path $SshKey)) {
    throw "Chave SSH nao encontrada: $SshKey"
}

$dirty = git status --short
if ($dirty) {
    Write-Host $dirty
    throw "Existem alteracoes locais. Faca commit antes do deploy."
}

Write-Host "Enviando main para o GitHub..."
git push origin $Branch

$remoteCommand = @"
set -euo pipefail
cd $RemoteDir
GIT_SSH_COMMAND='ssh -i $DeployKey -o StrictHostKeyChecking=accept-new' git pull --ff-only origin $Branch
docker compose up -d --build
sleep 10
docker compose ps
curl -fsS http://127.0.0.1:8000/health
curl -fsSI http://127.0.0.1:5173/ >/dev/null
"@

Write-Host "Atualizando servidor Oracle..."
ssh -i $SshKey -o StrictHostKeyChecking=accept-new $Remote $remoteCommand

Write-Host ""
Write-Host "Deploy concluido."
