
# tools/start_lobehub.ps1 - Demarre LobeHub self-hosted via Docker
# Port : 3210

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ComposePath = Join-Path $ScriptDir "..\docker\lobehub"

Write-Host "Demarrage de LobeHub (Nokido edition)..." -ForegroundColor Cyan
Set-Location $ComposePath

if (Get-Command "docker-compose" -ErrorAction SilentlyContinue) {
    docker-compose up -d
} else {
    docker compose up -d
}

Write-Host "`nLobeHub est en cours de demarrage sur http://localhost:3210" -ForegroundColor Green
Write-Host "Proxy configure sur host.docker.internal:8766" -ForegroundColor Gray
