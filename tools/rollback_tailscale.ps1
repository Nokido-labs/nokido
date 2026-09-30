# rollback_tailscale.ps1 - Restore NSSM AppParameters from sandbox/nssm-backups
#
# Reverts what migrate_to_tailscale.ps1 did:
#   1. Read latest backup file per service in LaForge/sandbox/nssm-backups/.
#   2. nssm set <svc> AppParameters <old>.
#   3. Restart service.
#   4. Verify LISTEN on 127.0.0.1.
#   5. Remove the LaForge-Tailnet-Inbound firewall rule.
#
# Run normal - script self-elevates via UAC.

$ErrorActionPreference = "Stop"

# Self-elevation
$current   = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal $current
$isAdmin   = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Not admin - relaunching via UAC..." -ForegroundColor Yellow
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-File", "`"$PSCommandPath`"")
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit
}

# --- Configuration ---------------------------------------------------------

$NSSM      = "C:\ProgramData\chocolatey\bin\nssm.exe"
$Nokido   = "$env:USERPROFILE\Script python IA\Nokido"
$BackupDir = Join-Path $Nokido "sandbox\nssm-backups"
$FwRule    = "LaForge-Tailnet-Inbound"

$Services = @(
    @{ Name = "NokidoMCP";          Ports = @(8766) },
    @{ Name = "NokidoWebHub";       Ports = @(7400) },
    @{ Name = "NokidoDenoHubMCP";   Ports = @(8769) },
    @{ Name = "NokidoDenoWebHub";   Ports = @(7401) },
    @{ Name = "NokidoDenoProxy";    Ports = @(8000) },
    @{ Name = "NokidoNetcfgMCP";    Ports = @(8767) }
)

# --- Pre-flight ------------------------------------------------------------

if (-not (Test-Path $NSSM)) { throw "NSSM not found at $NSSM" }
if (-not (Test-Path $BackupDir)) { throw "No backup directory at $BackupDir - nothing to roll back" }

Write-Host "[1/4] Locate latest backup per service..." -ForegroundColor Cyan
$Plan = @()
foreach ($svc in $Services) {
    $name = $svc.Name
    $existing = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "  SKIP $name (service not installed)" -ForegroundColor DarkYellow
        continue
    }
    $candidates = Get-ChildItem -Path $BackupDir -Filter "$name-*.txt" -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending
    if (-not $candidates -or $candidates.Count -eq 0) {
        Write-Host "  SKIP $name (no backup found)" -ForegroundColor DarkYellow
        continue
    }
    $latest = $candidates[0]
    $old    = (Get-Content -Path $latest.FullName -Raw).TrimEnd("`r","`n"," ")
    Write-Host "  $name <- $($latest.Name)"
    $Plan += @{ Name = $name; Backup = $latest.FullName; Params = $old; Ports = $svc.Ports }
}

if ($Plan.Count -eq 0) {
    Write-Host "Nothing to roll back." -ForegroundColor Yellow
    Write-Host "Press Enter to close..."
    [void][System.Console]::ReadLine()
    exit
}

# --- Restore ---------------------------------------------------------------

Write-Host "[2/4] Restore AppParameters + restart services..." -ForegroundColor Cyan
foreach ($p in $Plan) {
    Write-Host "  Stop  $($p.Name)"
    cmd /c "`"$NSSM`" stop $($p.Name)" 2>&1 | Out-Null
    Start-Sleep -Seconds 2

    & $NSSM set $p.Name AppParameters $p.Params | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERR  $($p.Name) failed to restore AppParameters" -ForegroundColor Red
        continue
    }
    Write-Host "  Restored $($p.Name)"
    Write-Host "    PARAMS: $($p.Params)" -ForegroundColor DarkGray

    & $NSSM start $p.Name | Out-Null
    Write-Host "  Start $($p.Name)"
}
Start-Sleep -Seconds 8

# --- Remove firewall rule --------------------------------------------------

Write-Host "[3/4] Remove firewall rule '$FwRule' if present..." -ForegroundColor Cyan
$existingRule = Get-NetFirewallRule -DisplayName $FwRule -ErrorAction SilentlyContinue
if ($existingRule) {
    Remove-NetFirewallRule -DisplayName $FwRule -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    Write-Host "  Removed '$FwRule'"
} else {
    Write-Host "  Rule '$FwRule' not present - skip"
}

# --- Verify ---------------------------------------------------------------

Write-Host "[4/4] Verify each port is LISTEN on 127.0.0.1..." -ForegroundColor Cyan
$AllOk = $true
foreach ($p in $Plan) {
    foreach ($port in $p.Ports) {
        $listen = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($listen) {
            Write-Host ("  OK   $($p.Name) 127.0.0.1:${port} (PID " + $listen.OwningProcess + ")") -ForegroundColor Green
        } else {
            Write-Host "  MISS $($p.Name) 127.0.0.1:${port} not listening" -ForegroundColor Yellow
            $AllOk = $false
        }
    }
}

Write-Host ""
if ($AllOk) {
    Write-Host "Rollback complete - all services back on 127.0.0.1." -ForegroundColor Green
} else {
    Write-Host "Rollback partial - check NSSM stderr logs for failing services." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
