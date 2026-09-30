# forge_nrem3_shutdown.ps1 — Fire cycle NREM3 + monitor trainers + glymphatic GC + shutdown auto
# Usage : powershell -ExecutionPolicy Bypass -File tools\forge_nrem3_shutdown.ps1
# Cancel shutdown pendant fenetre 60s : shutdown /a

param(
    [int]$MaxWaitMin = 90,
    [int]$PollEverySec = 60,
    [int]$IdleThresholdTicks = 3,
    [int]$ShutdownGraceSec = 60,
    [switch]$DryRun = $false
)

$ErrorActionPreference = "Continue"
$root = "$env:USERPROFILE\Script python IA\Nokido"
Set-Location $root

# Token : RAW bearer obligatoire pour supervisor.ts Deno (string compare,
# pas verify JWT). JWT serait rejete par length mismatch.
$tokLine = Get-Content "Nokido.env" -ErrorAction SilentlyContinue | Select-String "^FORGE_MCP_TOKEN"
if (-not $tokLine) { Write-Host "ERREUR: FORGE_MCP_TOKEN manquant Nokido.env" -ForegroundColor Red; exit 1 }
$tok = ($tokLine -split "=", 2)[1].Trim()
if ($tok.Length -lt 30) { Write-Host "ERREUR: tok len=$($tok.Length) invalide" -ForegroundColor Red; exit 1 }
Write-Host "Raw bearer len=$($tok.Length)" -ForegroundColor Green
$H = @{Authorization = "Bearer $tok"}

# Preflight : hub up ?
try {
    $health = (Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8766/health -TimeoutSec 5).Content
    Write-Host "Hub UP: $health" -ForegroundColor Green
} catch {
    Write-Host "ERREUR: hub :8766 inaccessible. Arret." -ForegroundColor Red; exit 2
}

# ========================================
# 1. FIRE NREM3
# ========================================
Write-Host "`n=== FIRE NREM3 ===" -ForegroundColor Cyan
try {
    $fire = (Invoke-WebRequest -UseBasicParsing -Headers $H -Method POST -Uri http://127.0.0.1:8765/supervisor/circadian/fire/NREM3 -TimeoutSec 60).Content
    Write-Host $fire
} catch {
    Write-Host "ERREUR fire NREM3: $($_.Exception.Message)" -ForegroundColor Red; exit 3
}
$fireTs = [int][double]::Parse((Get-Date -UFormat %s))
Write-Host "Fire ts=$fireTs MaxWait=${MaxWaitMin}min Poll=${PollEverySec}s"

# ========================================
# 2. MONITOR heartbeats trainers
# ========================================
Write-Host "`n=== MONITOR (idle threshold $IdleThresholdTicks ticks) ===" -ForegroundColor Cyan
$maxIter = [int](($MaxWaitMin * 60) / $PollEverySec)
$idleConsecutive = 0

for ($i=0; $i -lt $maxIter; $i++) {
    Start-Sleep $PollEverySec

    $offline = $null; $night = $null
    try { $offline = Get-Content "$root\sandbox\offline_trainer.heartbeat" -Raw | ConvertFrom-Json } catch {}
    try { $night = Get-Content "$root\sandbox\night_trainer.heartbeat" -Raw | ConvertFrom-Json } catch {}

    $now = [int][double]::Parse((Get-Date -UFormat %s))
    $offlineAge = if ($offline.ts) { $now - [int]$offline.ts } else { 99999 }
    $nightAge   = if ($night.ts)   { $now - [int]$night.ts   } else { 99999 }

    $ram = 0; $cpu = 0
    try {
        $snap = (Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8766/api/resource/state -TimeoutSec 5).Content | ConvertFrom-Json
        $ram = [int]$snap.snapshot.ram_pct; $cpu = [int]$snap.snapshot.cpu_pct
    } catch {}

    $elapsedMin = [int](($now - $fireTs) / 60)
    Write-Host "t+${elapsedMin}min RAM=${ram}% CPU=${cpu}% offline_age=${offlineAge}s night_age=${nightAge}s idle=$idleConsecutive/$IdleThresholdTicks"

    if ($offlineAge -gt 180 -and $nightAge -gt 180 -and $cpu -lt 30) {
        $idleConsecutive++
        if ($idleConsecutive -ge $IdleThresholdTicks) {
            Write-Host "`n=== NREM3 termine (trainers idle ${idleConsecutive}x${PollEverySec}s + CPU bas) ===" -ForegroundColor Green
            break
        }
    } else {
        $idleConsecutive = 0
    }
}

# ========================================
# 3. GLYMPHATIC GC manuel (VACUUM + rotate + backup critical_events)
# ========================================
Write-Host "`n=== GLYMPHATIC GC ===" -ForegroundColor Cyan
try {
    $gc = (Invoke-WebRequest -UseBasicParsing -Headers $H -Method POST -Uri http://127.0.0.1:8766/api/maintenance/gc -Body '{"vacuum":true,"rotate":true,"caches":true,"hormone":true}' -ContentType "application/json" -TimeoutSec 240).Content
    Write-Host $gc
} catch {
    Write-Host "GC failed (non-bloquant): $($_.Exception.Message)" -ForegroundColor Yellow
}

# ========================================
# 4. SHUTDOWN
# ========================================
if ($DryRun) {
    Write-Host "`n=== DRY-RUN : shutdown skip ===" -ForegroundColor Yellow
    exit 0
}

Write-Host "`n=== SHUTDOWN dans ${ShutdownGraceSec}s ===" -ForegroundColor Magenta
Write-Host "Pour annuler : shutdown /a" -ForegroundColor Yellow
shutdown /s /t $ShutdownGraceSec /c "Nokido NREM3 cycle termine - shutdown auto"
