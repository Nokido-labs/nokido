# migrate_services_user.ps1 - Migrate Nokido* services from LocalSystem to .\user
#
# Anomaly #5 from docs/SERVICES_REMEDIATION.md.
# All Nokido* NSSM services currently run as LocalSystem (SID S-1-5-18) which
# has near-root privileges. Migrating to user account .\user reduces attack
# surface (e.g. NokidoLlamaRouter exposes HTTP, NokidoDenoProxy has
# --allow-net --allow-run).
#
# [REQUIRES MANUAL PASSWORD INPUT] - this script will prompt for the Windows
# local password of user via Read-Host -AsSecureString. Do NOT hardcode.
#
# Strategy:
#   1. Pre-flight ACL audit on critical paths (RAG, logs, Ollama blobs, llama-server.exe).
#   2. Pilot: migrate NokidoRSSWatcher only, monitor 30s.
#   3. Confirmation prompt before rolling out to remaining services.
#   4. Rollback function ready if any service fails.
#
# Run normal - script self-elevates via UAC.

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

$NSSM    = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
$ACCOUNT = ".\user"
$PILOT   = "NokidoRSSWatcher"

# --- Helpers (idempotent NSSM wrappers) ---------------------------------
# All helpers swallow stderr-as-error from cmd /c (NSSM writes diagnostics
# to stderr even on success, which terminates under $ErrorActionPreference=Stop).
function Invoke-Nssm {
    param([Parameter(Mandatory)][string]$ArgLine)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = cmd /c "`"$NSSM`" $ArgLine" 2>&1
        return ($out | Out-String).Trim()
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Get-NssmStatus {
    param([Parameter(Mandatory)][string]$Svc)
    $s = Invoke-Nssm "status $Svc"
    # Possible values: SERVICE_RUNNING, SERVICE_STOPPED, SERVICE_PAUSED,
    # SERVICE_START_PENDING, SERVICE_STOP_PENDING, or empty if missing.
    return $s
}

function Get-NssmObjectName {
    param([Parameter(Mandatory)][string]$Svc)
    return (Invoke-Nssm "get $Svc ObjectName")
}

function Get-NssmStartType {
    param([Parameter(Mandatory)][string]$Svc)
    # Returns SERVICE_AUTO_START / SERVICE_DEMAND_START / SERVICE_DISABLED
    return (Invoke-Nssm "get $Svc Start")
}

function Stop-NssmIfRunning {
    param([Parameter(Mandatory)][string]$Svc)
    $st = Get-NssmStatus $Svc
    if ($st -match "SERVICE_RUNNING|SERVICE_PAUSED|SERVICE_START_PENDING") {
        [void](Invoke-Nssm "stop $Svc")
        Start-Sleep -Seconds 2
        return $true
    }
    return $false
}

# Full service list (pilot first, then the rest)
$ALL_SERVICES = @(
    "NokidoRSSWatcher",
    "NokidoMCP","NokidoWebHub","NokidoDenoHubMCP","NokidoDenoProxy",
    "NokidoDenoWebHub","NokidoLlamaNative","NokidoLlamaRouter",
    "NokidoAutonomousLoops","NokidoGeminiDaemon","NokidoGraph",
    "NokidoHebbian","NokidoHomeostasis"
)

if (-not (Test-Path $NSSM)) { throw "NSSM not found at $NSSM" }

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " Nokido services migration: LocalSystem -> $ACCOUNT" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# --- STEP 1: Pre-flight ACL audit ----------------------------------------
Write-Host "[1/4] Pre-flight ACL audit on critical paths..." -ForegroundColor Cyan
$PATHS = @(
    "$env:USERPROFILE\Script python IA\Nokido\RAG\embeddings.db",
    "$env:USERPROFILE\Script python IA\Nokido\logs",
    "$env:USERPROFILE\.ollama\models\blobs",
    "$env:USERPROFILE\miniforge3\python.exe",
    "$env:USERPROFILE\miniforge3\envs\laforge_py314\python.exe",
    "$env:USERPROFILE\llama-vulkan\llama-server.exe"
)
$aclProblems = @()
foreach ($p in $PATHS) {
    if (-not (Test-Path $p)) {
        Write-Host ("  [SKIP] $p (not present)") -ForegroundColor DarkGray
        continue
    }
    try {
        $acl = Get-Acl $p
        Write-Host ("  $p") -ForegroundColor Gray
        Write-Host ("    Owner: " + $acl.Owner)
        if ($acl.Owner -match "SYSTEM|Administrators") {
            $aclProblems += $p
            Write-Host "    WARN: owner is SYSTEM/Admin - run icacls before migration:" -ForegroundColor Yellow
            Write-Host ("    icacls `"$p`" /grant user:(M)") -ForegroundColor Yellow
        }
    } catch {
        Write-Host ("  [ERROR] Cannot read ACL on $p : $_") -ForegroundColor Red
    }
}

if ($aclProblems.Count -gt 0) {
    Write-Host ""
    Write-Host "ACL problems detected. Fix them before continuing? (y/N)" -ForegroundColor Yellow
    $resp = Read-Host
    if ($resp -ne "y") {
        Write-Host "Aborted." -ForegroundColor Red
        exit 1
    }
}

# --- STEP 2: Get password securely ---------------------------------------
Write-Host ""
Write-Host "[2/4] Enter Windows local password for $ACCOUNT" -ForegroundColor Cyan
Write-Host "(input is masked, use SecureString)" -ForegroundColor DarkGray
$securePwd = Read-Host -Prompt "Password" -AsSecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd)
$plainPwd = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

if ([string]::IsNullOrEmpty($plainPwd)) {
    Write-Host "Empty password - aborting." -ForegroundColor Red
    exit 1
}

# --- STEP 3: Pilot on NokidoRSSWatcher ----------------------------------
Write-Host ""
Write-Host "[3/4] PILOT: migrate $PILOT first..." -ForegroundColor Cyan
[void](Stop-NssmIfRunning $PILOT)
[void](Invoke-Nssm "set $PILOT ObjectName $ACCOUNT $plainPwd")
[void](Invoke-Nssm "start $PILOT")
Start-Sleep -Seconds 30
$status = Get-NssmStatus $PILOT
Write-Host ("  $PILOT status after 30s: " + $status)

$logErr = "$env:USERPROFILE\Script python IA\Nokido\logs\$PILOT.stderr.log"
if (Test-Path $logErr) {
    Write-Host "  Last 20 lines of stderr:" -ForegroundColor DarkGray
    Get-Content $logErr -Tail 20
}

if ($status -notmatch "SERVICE_RUNNING") {
    Write-Host ""
    Write-Host "PILOT FAILED. Rolling back $PILOT to LocalSystem..." -ForegroundColor Red
    [void](Stop-NssmIfRunning $PILOT)
    [void](Invoke-Nssm "set $PILOT ObjectName LocalSystem")
    [void](Invoke-Nssm "start $PILOT")
    Write-Host "Aborting global rollout. Investigate before retry." -ForegroundColor Red
    $plainPwd = $null
    exit 1
}

Write-Host "  PILOT OK." -ForegroundColor Green

# --- STEP 4: Confirm + rollout to remaining services ---------------------
Write-Host ""
Write-Host "[4/4] Pilot succeeded. Roll out to remaining services?" -ForegroundColor Cyan
Write-Host "Services to migrate:" -ForegroundColor Gray
$remaining = $ALL_SERVICES | Where-Object { $_ -ne $PILOT }
$remaining | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor Gray }
Write-Host ""
Write-Host "Proceed with global rollout? (y/N)" -ForegroundColor Yellow
$resp = Read-Host
if ($resp -ne "y") {
    Write-Host "Stopping at pilot only. $PILOT migrated, others unchanged." -ForegroundColor Yellow
    $plainPwd = $null
    exit 0
}

$failed   = @()
$skipped  = @()
$migrated = @()
foreach ($s in $remaining) {
    Write-Host ("  Migrating $s ...") -ForegroundColor Cyan

    # Idempotency: already migrated?
    $obj = Get-NssmObjectName $s
    if ($obj -match [regex]::Escape($ACCOUNT)) {
        Write-Host ("    SKIPPED: $s already runs as $ACCOUNT") -ForegroundColor DarkGray
        $skipped += $s
        continue
    }

    $startType = Get-NssmStartType $s
    $wasRunning = Stop-NssmIfRunning $s
    Start-Sleep -Seconds 1
    [void](Invoke-Nssm "set $s ObjectName $ACCOUNT $plainPwd")

    # If service is Manual and was stopped, do not start it - leave it stopped.
    if (($startType -match "SERVICE_DEMAND_START") -and (-not $wasRunning)) {
        Write-Host ("    OK: $s set to $ACCOUNT (Manual + stopped, left stopped)") -ForegroundColor Green
        $migrated += $s
        continue
    }

    [void](Invoke-Nssm "start $s")
    Start-Sleep -Seconds 5
    $st = Get-NssmStatus $s
    if ($st -notmatch "SERVICE_RUNNING") {
        Write-Host ("    FAILED: $s status=$st") -ForegroundColor Red
        $failed += $s
    } else {
        Write-Host ("    OK: $s running") -ForegroundColor Green
        $migrated += $s
    }
}

Write-Host ""
Write-Host ("Summary: " + $migrated.Count + " migrated, " + $skipped.Count + " skipped, " + $failed.Count + " failed.") -ForegroundColor Cyan

# Clear password from memory
$plainPwd = $null
[System.GC]::Collect()

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host "Failed services (still need rollback or investigation):" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor Red }
    Write-Host ""
    Write-Host "Rollback a single service with:" -ForegroundColor DarkGray
    Write-Host ("  & '$NSSM' stop <SVC>; & '$NSSM' set <SVC> ObjectName LocalSystem; & '$NSSM' start <SVC>") -ForegroundColor DarkGray
} else {
    Write-Host "All services migrated to $ACCOUNT successfully." -ForegroundColor Green
}

Write-Host ""
Write-Host "Global rollback (run as admin):" -ForegroundColor DarkGray
Write-Host ("  foreach (`$s in @('" + ($ALL_SERVICES -join "','") + "')) {") -ForegroundColor DarkGray
Write-Host ("    & '$NSSM' stop `$s; & '$NSSM' set `$s ObjectName LocalSystem; & '$NSSM' start `$s") -ForegroundColor DarkGray
Write-Host ("  }") -ForegroundColor DarkGray

Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
