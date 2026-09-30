# resume_migrate_services_user.ps1 - Resume Nokido* migration from LocalSystem to .\user
#
# Companion to tools/migrate_services_user.ps1. The original script crashed
# under $ErrorActionPreference=Stop because cmd /c "nssm stop <stopped-svc>"
# emits stderr that PowerShell treats as terminating (NativeCommandError).
#
# This script:
#   - Picks up where the original left off (skips already-migrated services).
#   - Tolerates SERVICE_STOPPED + Manual startup type (does not start them).
#   - Wraps every NSSM call in a Continue-mode helper so stderr does not abort.
#   - Reports SKIPPED / OK / FAILED per service.
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

# Services NOT yet migrated (from operator log of the failed run).
# NokidoHomeostasis was just migrated to py314 and is RUNNING - the
# idempotency check will skip it if its ObjectName already matches.
$REMAINING = @(
    "NokidoLlamaNative",
    "NokidoLlamaRouter",
    "NokidoAutonomousLoops",
    "NokidoGeminiDaemon",
    "NokidoGraph",
    "NokidoHebbian",
    "NokidoHomeostasis",
    "NokidoNetcfgMCP",
    "NokidoOpenAIProxy"
)

if (-not (Test-Path $NSSM)) { throw "NSSM not found at $NSSM" }

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " Nokido resume migration: LocalSystem -> $ACCOUNT" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# --- Helpers (idempotent NSSM wrappers) ---------------------------------
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
    return (Invoke-Nssm "status $Svc")
}

function Get-NssmObjectName {
    param([Parameter(Mandatory)][string]$Svc)
    return (Invoke-Nssm "get $Svc ObjectName")
}

function Get-NssmStartType {
    param([Parameter(Mandatory)][string]$Svc)
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

# --- Password prompt (same pattern as original) -------------------------
Write-Host "Enter Windows local password for $ACCOUNT" -ForegroundColor Cyan
Write-Host "(input is masked, use SecureString)" -ForegroundColor DarkGray
$securePwd = Read-Host -Prompt "Password" -AsSecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd)
$plainPwd = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

if ([string]::IsNullOrEmpty($plainPwd)) {
    Write-Host "Empty password - aborting." -ForegroundColor Red
    exit 1
}

# --- Migration loop ------------------------------------------------------
Write-Host ""
Write-Host "Resuming migration on " -NoNewline -ForegroundColor Cyan
Write-Host ($REMAINING.Count.ToString() + " service(s):") -ForegroundColor Cyan
$REMAINING | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor Gray }
Write-Host ""

$failed   = @()
$skipped  = @()
$migrated = @()
foreach ($s in $REMAINING) {
    Write-Host ("  Migrating $s ...") -ForegroundColor Cyan

    # Existence check
    $svcObj = Get-Service -Name $s -ErrorAction SilentlyContinue
    if (-not $svcObj) {
        Write-Host ("    SKIPPED: $s does not exist") -ForegroundColor DarkGray
        $skipped += $s
        continue
    }

    # Idempotency: already migrated?
    $obj = Get-NssmObjectName $s
    if ($obj -match [regex]::Escape($ACCOUNT)) {
        Write-Host ("    SKIPPED: $s already runs as $ACCOUNT (ObjectName=$obj)") -ForegroundColor DarkGray
        $skipped += $s
        continue
    }

    $startType  = Get-NssmStartType $s
    $wasRunning = Stop-NssmIfRunning $s
    Start-Sleep -Seconds 1

    $setOut = Invoke-Nssm "set $s ObjectName $ACCOUNT $plainPwd"
    if ($setOut -match "FAILURE|denied|invalid") {
        Write-Host ("    FAILED: nssm set returned: $setOut") -ForegroundColor Red
        $failed += $s
        continue
    }

    # If service is Manual and was stopped, do not start it.
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
        Write-Host ("    OK: $s running as $ACCOUNT") -ForegroundColor Green
        $migrated += $s
    }
}

# Clear password from memory (preserve original pattern)
$plainPwd = $null
[System.GC]::Collect()

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host (" Migrated: " + $migrated.Count) -ForegroundColor Green
Write-Host (" Skipped : " + $skipped.Count) -ForegroundColor DarkGray
Write-Host (" Failed  : " + $failed.Count) -ForegroundColor $(if ($failed.Count -gt 0) { "Red" } else { "DarkGray" })
Write-Host "==============================================" -ForegroundColor Cyan

if ($migrated.Count -gt 0) {
    Write-Host ""
    Write-Host "Migrated:" -ForegroundColor Green
    $migrated | ForEach-Object { Write-Host ("  + " + $_) -ForegroundColor Green }
}
if ($skipped.Count -gt 0) {
    Write-Host ""
    Write-Host "Skipped (already migrated or absent):" -ForegroundColor DarkGray
    $skipped | ForEach-Object { Write-Host ("  = " + $_) -ForegroundColor DarkGray }
}
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "Failed (still need rollback or investigation):" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor Red }
    Write-Host ""
    Write-Host "Rollback a single service with:" -ForegroundColor DarkGray
    Write-Host ("  & '$NSSM' stop <SVC>; & '$NSSM' set <SVC> ObjectName LocalSystem; & '$NSSM' start <SVC>") -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
