# fix_ollama_models_path.ps1 - Wrap ollama serve as NSSM service NokidoOllama
#
# Root cause (2026-05-02 reachability probe): ollama daemon launched from
# tray app does NOT inherit user-scope OLLAMA_MODELS=D:\ollama\models, so
# /api/tags returns 0 models while 13 model families exist on disk.
#
# Fix:
#   1. setx /M OLLAMA_MODELS "D:\ollama\models"  (machine scope, survives reboot)
#   2. Stop tray + ollama.exe
#   3. Install NSSM service NokidoOllama with explicit AppEnvironmentExtra
#      (OLLAMA_MODELS, OLLAMA_KEEP_ALIVE=30s, OLLAMA_MAX_LOADED_MODELS=1)
#   4. Disable Ollama tray startup shortcut if present (Start Menu/Startup)
#   5. Verify /api/tags returns models
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

$svc          = "NokidoOllama"
$ollamaExe    = "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama.exe"
$ollamaTray   = "$env:USERPROFILE\AppData\Local\Programs\Ollama\ollama app.exe"
$workDir      = "$env:USERPROFILE\AppData\Local\Programs\Ollama"
$logDir       = "$env:USERPROFILE\Script python IA\Nokido\logs"
$logOut       = Join-Path $logDir "ollama.stdout.log"
$logErr       = Join-Path $logDir "ollama.stderr.log"
$NSSM         = "C:\ProgramData\chocolatey\bin\nssm.exe"
$modelsDir    = "D:\ollama\models"
$keepAlive    = "30s"
$maxLoaded    = "1"
$ollamaHost   = "127.0.0.1:11434"
$port         = 11434
$startupLnk   = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Ollama.lnk"
$bakStartup   = $null

if (-not (Test-Path $NSSM))      { throw "NSSM not found at $NSSM" }
if (-not (Test-Path $ollamaExe)) { throw "ollama.exe not found at $ollamaExe" }
if (-not (Test-Path $modelsDir)) { throw "Models dir not found at $modelsDir" }
if (-not (Test-Path $logDir))    { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

Write-Host "[1/7] Set machine-scope OLLAMA_MODELS env var..." -ForegroundColor Cyan
$prev = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "Machine")
if ($prev -eq $modelsDir) {
    Write-Host "  Already set: $prev"
} else {
    [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $modelsDir, "Machine")
    Write-Host "  Set machine OLLAMA_MODELS=$modelsDir (was: $prev)"
}
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", $keepAlive, "Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS", $maxLoaded, "Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", $ollamaHost, "Machine")

Write-Host "[2/7] Stop + remove old service ($svc)..." -ForegroundColor Cyan
$existing = Get-Service -Name $svc -ErrorAction SilentlyContinue
if ($existing) {
    cmd /c "`"$NSSM`" stop $svc" 2>&1 | Out-Null
    cmd /c "`"$NSSM`" remove $svc confirm" 2>&1 | Out-Null
    Write-Host "  Old instance removed."
} else {
    Write-Host "  No old instance."
}

Write-Host "[3/7] Kill running ollama processes (tray + serve)..." -ForegroundColor Cyan
Get-Process -Name "ollama","ollama app" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host ("  kill PID " + $_.Id + " (" + $_.ProcessName + ")")
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
$listenPre = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listenPre) {
    Write-Host ("  port " + $port + " held by PID " + $listenPre.OwningProcess + " - killing")
    Stop-Process -Id $listenPre.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Write-Host "[4/7] Disable Ollama tray startup shortcut (if present)..." -ForegroundColor Cyan
if (Test-Path $startupLnk) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $bakStartup = "$startupLnk.disabled-$stamp"
    Move-Item $startupLnk $bakStartup -Force
    Write-Host ("  Moved -> " + $bakStartup)
} else {
    Write-Host "  No startup shortcut (tray launched manually or via Run key)."
}

Write-Host "[5/7] Install NSSM service $svc (ollama serve)..." -ForegroundColor Cyan
& $NSSM install $svc $ollamaExe serve
& $NSSM set $svc AppDirectory       $workDir
& $NSSM set $svc AppStdout          $logOut
& $NSSM set $svc AppStderr          $logErr
& $NSSM set $svc AppRotateFiles     1
& $NSSM set $svc AppRotateBytes     10485760
& $NSSM set $svc Start              SERVICE_AUTO_START
& $NSSM set $svc DisplayName        "Nokido Ollama daemon :11434"
& $NSSM set $svc Description        "ollama serve with OLLAMA_MODELS=D:\ollama\models, KEEP_ALIVE=30s, MAX_LOADED_MODELS=1"
& $NSSM set $svc AppRestartDelay    5000
& $NSSM set $svc AppExit Default    Restart

# Critical: explicit env so daemon sees D:\ollama\models even if machine env not yet propagated
$envBlock = @(
    "OLLAMA_MODELS=$modelsDir",
    "OLLAMA_KEEP_ALIVE=$keepAlive",
    "OLLAMA_MAX_LOADED_MODELS=$maxLoaded",
    "OLLAMA_HOST=$ollamaHost"
)
& $NSSM set $svc AppEnvironmentExtra $envBlock
Write-Host "  AppEnvironmentExtra set: $($envBlock -join ' ; ')"

Write-Host "[6/7] Start service $svc..." -ForegroundColor Cyan
& $NSSM start $svc
Start-Sleep -Seconds 4
$status = & $NSSM status $svc
Write-Host ("  Status: " + $status)

Write-Host "[7/7] Verify port $port LISTEN + /api/tags..." -ForegroundColor Cyan
$tries = 0
$listen = $null
while ($tries -lt 6 -and -not $listen) {
    Start-Sleep -Seconds 2
    $listen = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    $tries++
}
if ($listen) {
    Write-Host ("OK: Port " + $port + " LISTEN by PID " + $listen.OwningProcess) -ForegroundColor Green
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/api/tags" -TimeoutSec 10
        $json = $resp.Content | ConvertFrom-Json
        $count = ($json.models | Measure-Object).Count
        Write-Host ("  /api/tags -> HTTP " + $resp.StatusCode + " - " + $count + " models visible") -ForegroundColor Green
        if ($count -gt 0) {
            $json.models | Select-Object -First 5 | ForEach-Object { Write-Host ("    - " + $_.name) -ForegroundColor DarkGreen }
        }
    } catch {
        Write-Host ("  /api/tags probe FAILED: " + $_.Exception.Message) -ForegroundColor Yellow
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
Write-Host ("  [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', '$prev', 'Machine')") -ForegroundColor DarkGray
if ($bakStartup) {
    Write-Host ("  Move-Item '$bakStartup' '$startupLnk'") -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
