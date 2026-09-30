# install_openai_proxy_nssm.ps1 - Install forge_openai_proxy.py as silent NSSM service
#
# Service: NokidoOpenAIProxy
# Port   : 127.0.0.1:7777 (OpenAI-compat /v1/{models,chat/completions})
# Wraps  : Nokido hub :8766 ask tool for LobeHub / Cline / others
#
# Run normal - script self-elevates via UAC.

$ErrorActionPreference = "Stop"

# Self-elevation
$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal $current
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Not admin - relaunching via UAC..." -ForegroundColor Yellow
    $relArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`"")
    Start-Process powershell -Verb RunAs -ArgumentList $relArgs
    exit
}

$svc        = "NokidoOpenAIProxy"
$pythonExe  = "$env:USERPROFILE\miniforge3\python.exe"
$workDir    = "$env:USERPROFILE\Script python IA\Nokido"
$scriptRel  = "tools\forge_openai_proxy.py"
$scriptAbs  = Join-Path $workDir $scriptRel
$logDir     = Join-Path $workDir "logs"
$logOut     = Join-Path $logDir "openai_proxy.stdout.log"
$logErr     = Join-Path $logDir "openai_proxy.stderr.log"
$NSSM       = "C:\ProgramData\chocolatey\bin\nssm.exe"
$port       = 7777

if (-not (Test-Path $NSSM))      { throw "NSSM not found at $NSSM" }
if (-not (Test-Path $pythonExe)) { throw "Python not found at $pythonExe" }
if (-not (Test-Path $scriptAbs)) { throw "Proxy script not found at $scriptAbs" }
if (-not (Test-Path $logDir))    { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

Write-Host "[1/5] Stop + remove old instance ($svc)..." -ForegroundColor Cyan
$existing = Get-Service -Name $svc -ErrorAction SilentlyContinue
if ($existing) {
    cmd /c "`"$NSSM`" stop $svc" 2>&1 | Out-Null
    cmd /c "`"$NSSM`" remove $svc confirm" 2>&1 | Out-Null
    Write-Host "  Old instance removed."
} else {
    Write-Host "  No old instance."
}

Write-Host "[2/5] Install service $svc..." -ForegroundColor Cyan
cmd /c "`"$NSSM`" install $svc `"$pythonExe`" $scriptRel" | Out-Null
cmd /c "`"$NSSM`" set $svc AppDirectory `"$workDir`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppStdout `"$logOut`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppStderr `"$logErr`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppRotateFiles 1" | Out-Null
cmd /c "`"$NSSM`" set $svc AppRotateBytes 10485760" | Out-Null
cmd /c "`"$NSSM`" set $svc Start SERVICE_AUTO_START" | Out-Null
cmd /c "`"$NSSM`" set $svc DisplayName `"Nokido OpenAI-compat Proxy :7777`"" | Out-Null
cmd /c "`"$NSSM`" set $svc Description `"OpenAI-compat multi-provider proxy for LobeHub / Cline / others`"" | Out-Null
cmd /c "`"$NSSM`" set $svc AppRestartDelay 5000" | Out-Null
cmd /c "`"$NSSM`" set $svc AppExit Default Restart" | Out-Null
Write-Host "  Service registered."

Write-Host "[3/5] Kill orphan python processes running forge_openai_proxy..." -ForegroundColor Cyan
$cims = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
foreach ($p in $cims) {
    if ($p.CommandLine -and $p.CommandLine -match "forge_openai_proxy") {
        Write-Host ("  kill PID " + $p.ProcessId)
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
$listenPre = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listenPre) {
    Write-Host ("  port " + $port + " was held by PID " + $listenPre.OwningProcess + " - killing")
    Stop-Process -Id $listenPre.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Write-Host "[4/5] Start service..." -ForegroundColor Cyan
cmd /c "`"$NSSM`" start $svc" | Out-Null
Start-Sleep -Seconds 6
$status = cmd /c "`"$NSSM`" status $svc"
Write-Host ("  Status: " + $status)

Write-Host "[5/5] Verify port $port LISTEN..." -ForegroundColor Cyan
$tries = 0
$listen = $null
while ($tries -lt 5 -and -not $listen) {
    Start-Sleep -Seconds 2
    $listen = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    $tries++
}
if ($listen) {
    Write-Host ("OK: Port " + $port + " LISTEN by PID " + $listen.OwningProcess) -ForegroundColor Green
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:" + $port + "/v1/models") -TimeoutSec 5
        Write-Host ("  /v1/models -> HTTP " + $resp.StatusCode + " (" + $resp.Content.Length + " bytes)") -ForegroundColor Green
    } catch {
        Write-Host ("  /v1/models probe FAILED: " + $_.Exception.Message) -ForegroundColor Yellow
    }
} else {
    Write-Host ("WARN: Port " + $port + " not in LISTEN. Tail of " + $logErr + ":") -ForegroundColor Yellow
    if (Test-Path $logErr) {
        Get-Content $logErr -Tail 30 | ForEach-Object { Write-Host ("    " + $_) -ForegroundColor DarkYellow }
    }
}

Write-Host ""
Write-Host "Rollback commands:" -ForegroundColor DarkGray
Write-Host ("  nssm stop $svc; nssm remove $svc confirm") -ForegroundColor DarkGray

Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
