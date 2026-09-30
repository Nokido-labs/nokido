# install_watchdog_nssm.ps1 — Installe forge_service_watchdog comme service NSSM
# REQUIRES: admin shell
# Usage: .\tools\install_watchdog_nssm.ps1

param(
    [string]$ServiceName = "NokidoWatchdog",
    [int]$IntervalSeconds = 30,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$NSSM = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
$PYTHON = "$env:USERPROFILE\miniforge3\python.exe"
$ROOT = "$env:USERPROFILE\Script python IA\Nokido"
$SCRIPT = "$ROOT\app\forge_service_watchdog.py"

if (-not (Test-Path $NSSM)) { throw "NSSM not found: $NSSM" }
if (-not (Test-Path $PYTHON)) { throw "LAFORGE_PYTHON not found: $PYTHON" }

$dryFlag = if ($DryRun) { "--dry-run" } else { "" }
$appArgs = "$SCRIPT --interval $IntervalSeconds $dryFlag".Trim()

Write-Host "Installing $ServiceName ..."
& $NSSM install $ServiceName $PYTHON $appArgs
& $NSSM set $ServiceName AppDirectory $ROOT
& $NSSM set $ServiceName AppStdout "$ROOT\logs\watchdog.stdout.log"
& $NSSM set $ServiceName AppStderr "$ROOT\logs\watchdog.stderr.log"
& $NSSM set $ServiceName AppRotateFiles 1
& $NSSM set $ServiceName AppRotateBytes 5242880
& $NSSM set $ServiceName AppRestartDelay 10000
& $NSSM set $ServiceName Start SERVICE_AUTO_START
# Run as LocalSystem so restart strategies A+B (nssm/Restart-Service) have admin rights
& $NSSM set $ServiceName ObjectName LocalSystem

Write-Host "Starting $ServiceName ..."
& $NSSM start $ServiceName

Write-Host "Done. Status:"
Get-Service -Name $ServiceName | Format-Table Name, Status, StartType
