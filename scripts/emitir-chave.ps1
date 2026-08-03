[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Referencia,

    [string]$NomeCliente = "",
    [string]$EmailCliente = "",
    [string]$DiscordClienteId = ""
)

$ErrorActionPreference = "Stop"

$remote = "ubuntu@163.176.143.142"
$projectRoot = Split-Path -Parent $PSScriptRoot
$userProfileDir = [Environment]::GetFolderPath("UserProfile")
$keyCandidates = @(
    (Join-Path $projectRoot "..\Morro do Mineiro Bot\oracle.key"),
    (Join-Path $userProfileDir ".ssh\yuno_oracle_ed25519"),
    (Join-Path $projectRoot "..\Bot Discord\oracle.key")
)
$sshKey = $keyCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $sshKey) {
    throw "Chave SSH do servidor Yuno nao encontrada."
}

$body = @{
    reference = $Referencia.Trim()
    customer_name = if ($NomeCliente.Trim()) { $NomeCliente.Trim() } else { $null }
    customer_email = if ($EmailCliente.Trim()) { $EmailCliente.Trim() } else { $null }
    customer_discord_user_id = if ($DiscordClienteId.Trim()) { $DiscordClienteId.Trim() } else { $null }
} | ConvertTo-Json -Compress
$payloadBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($body))

$remoteCommand = "cd /home/ubuntu/yuno && set -a && . ./.env && set +a && payload=`$(printf '%s' '$payloadBase64' | base64 -d) && curl -fsS -X POST http://127.0.0.1:8000/licenses/issue -H 'Content-Type: application/json' -H `"x-yuno-admin-token: `$ADMIN_TOKEN`" --data-binary `"`$payload`""
$raw = & ssh -i $sshKey -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new $remote $remoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "A API nao conseguiu emitir a chave. Confira a referencia e o status do servidor."
}

$license = $raw | ConvertFrom-Json
Write-Host "Chave emitida com sucesso." -ForegroundColor Green
Write-Host "Referencia: $($license.payment_reference)"
Write-Host "Status: $($license.status)"
Write-Host "Chave: $($license.key)" -ForegroundColor Yellow
$license
