# migrate_homeostasis_py314.ps1 - Switch NokidoHomeostasis NSSM service to py314 env
#
# Anomaly #3 from docs/SERVICES_REMEDIATION.md.
# Currently NokidoHomeostasis uses miniforge3 (3.12) while 4 sister services
# (Graph, Hebbian, RSSWatcher, GeminiDaemon) run on laforge_py314.
# Sanity test 2026-05-02: import forge_homeostasis_orchestrator on py314 = OK.
#
# [NEEDS ADMIN] - script self-elevates via UAC.

$ErrorActionPreference = "Stop"

# Self-elevation
$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal $current
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Not admin - relaunching via UAC..." -ForegroundColor Yellow
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`"")
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit
}

$svc      = "NokidoHomeostasis"
$NSSM     = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
$PY314    = "$env:USERPROFILE\miniforge3\envs\laforge_py314\python.exe"
$PY312    = "$env:USERPROFILE\miniforge3\python.exe"
$logDir   = "$env:USERPROFILE\Script python IA\Nokido\logs"
$logErr   = Join-Path $logDir "$svc.stderr.log"

if (-not (Test-Path $NSSM))  { throw "NSSM not found at $NSSM" }
if (-not (Test-Path $PY314)) { throw "py314 interpreter not found at $PY314" }

Write-Host "[1/6] Pre-flight: smoke test import on py314..." -ForegroundColor Cyan
$env:PYTHONNOUSERSITE = "1"
$smoke = & $PY314 -c "import sys; sys.path.insert(0, r'$env:USERPROFILE\Script python IA\Nokido\app'); import forge_homeostasis_orchestrator; print('OK')"
if ($smoke -ne "OK") {
    throw "Smoke test FAILED on py314 - aborting migration. Output: $smoke"
}
Write-Host "  Smoke test OK on py314." -ForegroundColor Green

Write-Host "[2/6] Show current service config..." -ForegroundColor Cyan
$currentApp = cmd /c "`"$NSSM`" get $svc Application"
Write-Host ("  Current Application: " + $currentApp)

Write-Host "[3/6] Stop service..." -ForegroundColor Cyan
cmd /c "`"$NSSM`" stop $svc" 2>&1 | Out-Null
Start-Sleep -Seconds 2

Write-Host "[4/6] Switch interpreter to py314..." -ForegroundColor Cyan
cmd /c "`"$NSSM`" set $svc Application `"$PY314`""
cmd /c "`"$NSSM`" set $svc AppEnvironmentExtra PYTHONNOUSERSITE=1"

Write-Host "[5/6] Verify new config..." -ForegroundColor Cyan
$newApp = cmd /c "`"$NSSM`" get $svc Application"
Write-Host ("  New Application: " + $newApp)

Write-Host "[6/6] Start service + monitor 30s..." -ForegroundColor Cyan
cmd /c "`"$NSSM`" start $svc"
Start-Sleep -Seconds 30
$status = cmd /c "`"$NSSM`" status $svc"
Write-Host ("  Status: " + $status)

if (Test-Path $logErr) {
    Write-Host "  Last 20 lines of stderr:" -ForegroundColor DarkGray
    Get-Content $logErr -Tail 20
}

Write-Host ""
Write-Host "Rollback (run as admin):" -ForegroundColor DarkGray
Write-Host ("  & '$NSSM' stop $svc") -ForegroundColor DarkGray
Write-Host ("  & '$NSSM' set $svc Application '$PY312'") -ForegroundColor DarkGray
Write-Host ("  & '$NSSM' set $svc AppEnvironmentExtra ''") -ForegroundColor DarkGray
Write-Host ("  & '$NSSM' start $svc") -ForegroundColor DarkGray

Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
