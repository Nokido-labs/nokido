# install_self_patcher_nssm.ps1 - Install forge_self_patcher.py as NSSM daemon
#
# Service: NokidoSelfPatcher
# Role   : Autonomous self-patching loop (1h cycle)
#          proposals -> deterministic rules + LLM patch -> tests -> git commit
#
# Run as normal user - self-elevates via UAC.

$ErrorActionPreference = "Stop"

$current   = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal $current
$isAdmin   = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Not admin - relaunching via UAC..." -ForegroundColor Yellow
    $relArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`"")
    Start-Process powershell -Verb RunAs -ArgumentList $relArgs
    exit
}

$svc       = "NokidoSelfPatcher"
$pythonExe = "$env:USERPROFILE\miniforge3\python.exe"
$workDir   = "$env:USERPROFILE\Script python IA\Nokido"
$scriptRel = "tools\forge_self_patcher.py"
$scriptAbs = Join-Path $workDir $scriptRel
$logDir    = Join-Path $workDir "logs"
$logOut    = Join-Path $logDir "self_patcher.stdout.log"
$logErr    = Join-Path $logDir "self_patcher.stderr.log"
$NSSM      = "C:\ProgramData\chocolatey\bin\nssm.exe"
$heartbeat = Join-Path $workDir "sandbox\self_patcher.heartbeat"

if (-not (Test-Path $NSSM))      { throw "NSSM not found at $NSSM" }
if (-not (Test-Path $pythonExe)) { throw "Python not found at $pythonExe" }
if (-not (Test-Path $scriptAbs)) { throw "Script not found at $scriptAbs" }
if (-not (Test-Path $logDir))    { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

Write-Host "[1/4] Stop + remove old instance ($svc)..." -ForegroundColor Cyan
$existing = Get-Service -Name $svc -ErrorAction SilentlyContinue
if ($existing) {
    cmd /c "`"$NSSM`" stop $svc" 2>&1 | Out-Null
    cmd /c "`"$NSSM`" remove $svc confirm" 2>&1 | Out-Null
    Write-Host "  Old instance removed."
} else {
    Write-Host "  No old instance."
}

Write-Host "[2/4] Install service $svc..." -ForegroundColor Cyan
cmd /c "`"$NSSM`" install $svc `"$pythonExe`" `"$scriptRel --daemon`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppDirectory `"$workDir`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppParameters `"$scriptRel --daemon`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppStdout `"$logOut`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppStderr `"$logErr`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppRotateFiles 1" | Out-Null
cmd /c "`"$NSSM`" set $svc AppRotateBytes 10485760" | Out-Null
cmd /c "`"$NSSM`" set $svc Start SERVICE_AUTO_START" | Out-Null
cmd /c "`"$NSSM`" set $svc DisplayName `"Nokido Self-Patcher (1h cycle)`"" | Out-Null
cmd /c "`"$NSSM`" set $svc Description `"Reads proposals -> deterministic rules + LLM -> tests -> git commit if pass`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppRestartDelay 60000" | Out-Null
cmd /c "`"$NSSM`" set $svc AppExit Default Restart" | Out-Null
cmd /c "`"$NSSM`" set $svc AppEnvironmentExtra PYTHONIOENCODING=utf-8" | Out-Null
Write-Host "  Service registered."

Write-Host "[3/4] Start service..." -ForegroundColor Cyan
cmd /c "`"$NSSM`" start $svc" | Out-Null
Start-Sleep -Seconds 5
$status = cmd /c "`"$NSSM`" status $svc"
Write-Host ("  Status: " + $status)

Write-Host "[4/4] Verify heartbeat (wait up to 30s)..." -ForegroundColor Cyan
$tries = 0
$ok = $false
while ($tries -lt 15 -and -not $ok) {
    Start-Sleep -Seconds 2
    if (Test-Path $heartbeat) { $ok = $true }
    $tries++
}
if ($ok) {
    $hb = Get-Content $heartbeat -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
    Write-Host ("OK: heartbeat at " + $hb.ts) -ForegroundColor Green
} else {
    Write-Host "WARN: no heartbeat yet (check logs)." -ForegroundColor Yellow
    Write-Host ("      Check logs: " + $logErr) -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "Dry-run test: & `"$pythonExe`" `"$scriptAbs`" --once --dry-run"
Write-Host "Rollback: nssm stop $svc; nssm remove $svc confirm" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
