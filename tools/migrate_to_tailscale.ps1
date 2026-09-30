# migrate_to_tailscale.ps1 - Migrate Nokido NSSM services from 127.0.0.1 to tailnet IP
#
# Before: each NSSM service binds 127.0.0.1, only local access
# After : binds the Tailscale interface IP (100.x.y.z), reachable across tailnet
#
# Bearer token auth STAYS mandatory at the app layer. Tailscale only adds
# network reachability + WireGuard encryption + ACL.
#
# Run normal - script self-elevates via UAC.
# Pre-reqs documented in LaForge\docs\TAILSCALE_MIGRATION.md.

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
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$FwRule    = "LaForge-Tailnet-Inbound"
$Tailnet   = "100.64.0.0/10"

# Services to migrate: name -> ports list (used for firewall + verification)
$Services = @(
    @{ Name = "NokidoMCP";          Ports = @(8766) },
    @{ Name = "NokidoWebHub";       Ports = @(7400) },
    @{ Name = "NokidoDenoHubMCP";   Ports = @(8769) },
    @{ Name = "NokidoDenoWebHub";   Ports = @(7401) },
    @{ Name = "NokidoDenoProxy";    Ports = @(8000) },
    @{ Name = "NokidoNetcfgMCP";    Ports = @(8767) }
)

# --- Pre-flight checks -----------------------------------------------------

if (-not (Test-Path $NSSM)) { throw "NSSM not found at $NSSM" }
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

Write-Host "[1/7] Detect Tailscale IP..." -ForegroundColor Cyan
$tsCmd = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $tsCmd) { throw "tailscale CLI not found in PATH. Install Tailscale first." }

$rawIp = & tailscale ip -4 2>&1
if ($LASTEXITCODE -ne 0) { throw "tailscale ip -4 failed: $rawIp" }

$TailnetIp = ($rawIp | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" } | Select-Object -First 1).Trim()
if (-not $TailnetIp) { throw "No tailnet IPv4 found in 'tailscale ip -4' output: $rawIp" }
if ($TailnetIp -notmatch "^100\.") {
    Write-Host "  WARN: detected IP $TailnetIp does not look like a CGNAT/tailnet IP" -ForegroundColor Yellow
}
Write-Host "  Tailnet IP = $TailnetIp" -ForegroundColor Green

# --- Backup + patch loop ---------------------------------------------------

Write-Host "[2/7] Backup AppParameters of each service..." -ForegroundColor Cyan
$BackupPaths = @{}
foreach ($svc in $Services) {
    $name = $svc.Name
    $existing = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "  SKIP $name (service not installed)" -ForegroundColor DarkYellow
        continue
    }
    $params = & $NSSM get $name AppParameters 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARN $name AppParameters fetch failed: $params" -ForegroundColor Yellow
        continue
    }
    $bakFile = Join-Path $BackupDir "$name-$Timestamp.txt"
    $params | Out-File -FilePath $bakFile -Encoding ASCII
    $BackupPaths[$name] = $bakFile
    Write-Host "  Saved $name -> $bakFile"
}

Write-Host "[3/7] Patch AppParameters (127.0.0.1 -> $TailnetIp)..." -ForegroundColor Cyan
$Patched = @()
foreach ($svc in $Services) {
    $name = $svc.Name
    if (-not $BackupPaths.ContainsKey($name)) { continue }
    $old = Get-Content -Path $BackupPaths[$name] -Raw
    $old = $old.TrimEnd("`r","`n"," ")
    if ($old -notmatch "127\.0\.0\.1") {
        Write-Host "  SKIP $name (no 127.0.0.1 found in current AppParameters)" -ForegroundColor DarkYellow
        continue
    }
    $new = $old -replace "127\.0\.0\.1", $TailnetIp
    if ($new -eq $old) {
        Write-Host "  SKIP $name (no change after replace)" -ForegroundColor DarkYellow
        continue
    }
    & $NSSM set $name AppParameters $new | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERR  $name failed to set AppParameters" -ForegroundColor Red
        continue
    }
    Write-Host "  Patched $name"
    Write-Host "    OLD: $old" -ForegroundColor DarkGray
    Write-Host "    NEW: $new" -ForegroundColor DarkGray
    $Patched += $svc
}

# --- Firewall rule ---------------------------------------------------------

Write-Host "[4/7] Add Windows Firewall inbound rule from tailnet ($Tailnet)..." -ForegroundColor Cyan
$existingRule = Get-NetFirewallRule -DisplayName $FwRule -ErrorAction SilentlyContinue
if ($existingRule) {
    Write-Host "  Rule '$FwRule' already exists - removing to recreate fresh"
    Remove-NetFirewallRule -DisplayName $FwRule -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
}

$AllPorts = @()
foreach ($svc in $Patched) { $AllPorts += $svc.Ports }
$AllPorts = $AllPorts | Sort-Object -Unique

if ($AllPorts.Count -gt 0) {
    New-NetFirewallRule `
        -DisplayName  $FwRule `
        -Description  "Nokido services reachable from Tailscale tailnet only" `
        -Direction    Inbound `
        -Action       Allow `
        -Protocol     TCP `
        -LocalPort    $AllPorts `
        -RemoteAddress $Tailnet `
        -Profile      Any | Out-Null
    Write-Host "  Created '$FwRule' on TCP ports: $($AllPorts -join ',') from $Tailnet"
} else {
    Write-Host "  No ports patched - skipping firewall rule" -ForegroundColor DarkYellow
}

# --- Restart services ------------------------------------------------------

Write-Host "[5/7] Restart patched services..." -ForegroundColor Cyan
foreach ($svc in $Patched) {
    $name = $svc.Name
    Write-Host "  Stop  $name"
    cmd /c "`"$NSSM`" stop $name" 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "  Start $name"
    & $NSSM start $name | Out-Null
}
Start-Sleep -Seconds 8

# --- Verify ----------------------------------------------------------------

Write-Host "[6/7] Verify each port is LISTEN on $TailnetIp..." -ForegroundColor Cyan
$AllOk = $true
foreach ($svc in $Patched) {
    foreach ($p in $svc.Ports) {
        $listen = Get-NetTCPConnection -LocalAddress $TailnetIp -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($listen) {
            Write-Host ("  OK   $($svc.Name) ${TailnetIp}:${p} (PID " + $listen.OwningProcess + ")") -ForegroundColor Green
        } else {
            Write-Host "  MISS $($svc.Name) ${TailnetIp}:${p} not listening" -ForegroundColor Yellow
            $AllOk = $false
        }
    }
}

# --- Summary + rollback hint ----------------------------------------------

Write-Host "[7/7] Done." -ForegroundColor Cyan
Write-Host ""
Write-Host "Tailnet IP : $TailnetIp" -ForegroundColor White
Write-Host "Backups    : $BackupDir" -ForegroundColor White
Write-Host "Firewall   : $FwRule (allow TCP $($AllPorts -join ',') from $Tailnet)" -ForegroundColor White
Write-Host ""
if ($AllOk) {
    Write-Host "All patched services are LISTEN on the tailnet IP." -ForegroundColor Green
} else {
    Write-Host "Some services did not bind on $TailnetIp - check NSSM logs." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Manual follow-up (NOT done by this script):" -ForegroundColor DarkGray
Write-Host "  - Ollama   : setx OLLAMA_HOST `"${TailnetIp}:11434`" /M ; restart Ollama" -ForegroundColor DarkGray
Write-Host "  - llama.cpp: edit NSSM AppParameters of llamacpp_native services if used" -ForegroundColor DarkGray
Write-Host "  - LM Studio: GUI > Local Server > Network > bind to ${TailnetIp}" -ForegroundColor DarkGray
Write-Host "  - Clients  : update LAFORGE_HUB_URL=http://${TailnetIp}:8766 and OLLAMA_HOST" -ForegroundColor DarkGray
Write-Host "  - ACL      : confirm tag:laforge-host / tag:laforge-agent set in Admin console" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Rollback :" -ForegroundColor DarkGray
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$LaForge\tools\rollback_tailscale.ps1`"" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Press Enter to close..."
[void][System.Console]::ReadLine()
