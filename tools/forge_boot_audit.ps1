
# forge_boot_audit.ps1 - inventaire complet de ce qui demarre auto sur Windows + Audit Nokido
# Run : powershell -ExecutionPolicy Bypass -File forge_boot_audit.ps1
#       -OutFile boot_audit.md  (default : stdout)
#       -Json                   (output JSON instead of MD)

param(
    [string]$OutFile = "",
    [switch]$Categorize,
    [switch]$Json
)

$ErrorActionPreference = "Continue"

$results = @{
    nssm_nokido = @()
    services = @()
    scheduled_tasks = @()
    registry_run = @()
    startup_folders = @()
    drivers_boot = @()
    network_audit = @{
        exposed_ports = @()
        bind_global_files = @()
    }
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Nokido Boot Audit & Security Scan (Unified)" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# --- 1. NSSM SERVICES (Current Logic) ---
Write-Host "`n[1/7] Verification des services NSSM Nokido..." -ForegroundColor Yellow
$nssm_services = @(Get-Service -Name "Nokido*" -ErrorAction SilentlyContinue)

if ($nssm_services.Count -eq 0) {
    Write-Host "Aucun service Nokido NSSM detecte." -ForegroundColor Red
} else {
    foreach ($svc in $nssm_services) {
        $results.nssm_nokido += [PSCustomObject]@{
            Name   = $svc.Name
            Status = $svc.Status
        }
        if ($svc.Name -eq "LaForge-Master") {
            Write-Host "Le superviseur unifie $($svc.Name) est installe (Statut: $($svc.Status))." -ForegroundColor Green
        } elseif ($svc.Status -eq "Running") {
            Write-Host "Avertissement: L'ancien service $($svc.Name) tourne encore en parallele !" -ForegroundColor Red
        }
    }
}

# --- 2. AUTO-START SERVICES (Old Logic) ---
Write-Host "`n[2/7] Services auto-start generaux..." -ForegroundColor Cyan
Get-Service | Where-Object { $_.StartType -in 'Automatic','AutomaticDelayedStart','Boot','System' } | ForEach-Object {
    $cim = Get-CimInstance Win32_Service -Filter "Name='$($_.Name)'" -ErrorAction SilentlyContinue
    $results.services += [PSCustomObject]@{
        Name      = $_.Name
        Display   = $_.DisplayName
        StartType = $_.StartType
        Status    = $_.Status
        Path      = if ($cim) { $cim.PathName } else { "" }
        Account   = if ($cim) { $cim.StartName } else { "" }
    }
}

# --- 3. SCHEDULED TASKS (Old Logic) ---
Write-Host "[3/7] Scheduled tasks (boot/logon)..." -ForegroundColor Cyan
Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.State -in 'Ready','Running' -and $_.Triggers -ne $null
} | ForEach-Object {
    $hasBootOrLogon = $_.Triggers | Where-Object { $_.CimClass.CimClassName -in 'MSFT_TaskLogonTrigger','MSFT_TaskBootTrigger' }
    if ($hasBootOrLogon) {
        $action = ($_.Actions | Select-Object -First 1)
        $results.scheduled_tasks += [PSCustomObject]@{
            Name    = $_.TaskName
            Path    = $_.TaskPath
            State   = $_.State
            Trigger = ($_.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ','   
            Execute = $action.Execute
            Args    = $action.Arguments
        }
    }
}

# --- 4. REGISTRY RUN KEYS (Old Logic) ---
Write-Host "[4/7] Registry Run keys..." -ForegroundColor Cyan
$runKeys = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Run",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"
)
foreach ($key in $runKeys) {
    if (Test-Path $key) {
        $props = Get-ItemProperty $key -ErrorAction SilentlyContinue
        $props.PSObject.Properties | Where-Object { $_.Name -notmatch '^PS' } | ForEach-Object {
            $results.registry_run += [PSCustomObject]@{
                Hive  = if ($key -match 'HKLM') { 'HKLM' } else { 'HKCU' }
                Key   = ($key -split '\\')[-1]
                Name  = $_.Name
                Value = $_.Value
            }
        }
    }
}

# --- 5. STARTUP FOLDERS (Old Logic) ---
Write-Host "[5/7] Startup folders..." -ForegroundColor Cyan
$startupFolders = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
    "$env:ALLUSERSPROFILE\Microsoft\Windows\Start Menu\Programs\StartUp"
)
foreach ($f in $startupFolders) {
    if (Test-Path $f) {
        Get-ChildItem $f -Force -ErrorAction SilentlyContinue | ForEach-Object {
            $results.startup_folders += [PSCustomObject]@{
                Folder = if ($f -match 'AllUsers') { 'AllUsers' } else { 'PerUser' }
                Name   = $_.Name
                Target = $_.FullName
            }
        }
    }
}

# --- 6. NETWORK AUDIT (Current Logic) ---
Write-Host "`n[6/7] Audit des ports en ecoute sur 0.0.0.0..." -ForegroundColor Yellow
$open_ports = netstat -ano | Select-String "0.0.0.0:" | Select-String "LISTENING"
foreach ($line in $open_ports) {
    if ($line -match "0\.0\.0\.0:8000" -or $line -match "0\.0\.0\.0:8765" -or $line -match "0\.0\.0\.0:8766" -or $line -match "0\.0\.0\.0:5557") {
        $results.network_audit.exposed_ports += $line.ToString().Trim()
        Write-Host "PORTS CRITIQUE EXPOSE : $line" -ForegroundColor Red
    }
}

# --- 7. BIND 0.0.0.0 SCAN (Current Logic) ---
Write-Host "`n[7/7] Scan occurrences 0.0.0.0 dans le code..." -ForegroundColor Yellow
try {
    $matches = Select-String -Path "*.py", "*.ts" -Pattern "0\.0\.0\.0" -Exclude "forge_boot_audit.ps1" -ErrorAction SilentlyContinue
    if ($matches) {
        foreach ($m in $matches) {
            $results.network_audit.bind_global_files += [PSCustomObject]@{
                File = $m.FileName
                Line = $m.LineNumber
                Text = $m.Line.Trim()
            }
        }
        Write-Host "Avertissement: Bind global detecte dans $($matches.Count) fichiers." -ForegroundColor Red
    }
} catch {}

# --- OUTPUT GENERATION ---

if ($Json) {
    $json = $results | ConvertTo-Json -Depth 5
    if ($OutFile) { $json | Out-File -Encoding utf8 $OutFile } else { $json }
    return
}

$lines = @()
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm'
$lines += "# Nokido Boot Audit - $ts"
$lines += ""
$lines += "## Vue ensemble"
$lines += ""
$lines += "| Source | Count |"
$lines += "|---|---|"
$lines += "| Services NSSM Nokido | $($results.nssm_nokido.Count) |"
$lines += "| Services auto-start generaux | $($results.services.Count) |"
$lines += "| Scheduled tasks (logon/boot) | $($results.scheduled_tasks.Count) |"
$lines += "| Registry Run keys | $($results.registry_run.Count) |"
$lines += "| Startup folders | $($results.startup_folders.Count) |"
$lines += "| Ports exposes (0.0.0.0) | $($results.network_audit.exposed_ports.Count) |"
$lines += ""

$lines += "## Services NSSM Nokido"
$lines += ""
foreach ($s in $results.nssm_nokido) {
    $color = if ($s.Status -eq "Running") { "Green" } else { "Gray" }
    $lines += "- **$($s.Name)** : $($s.Status)"
}
$lines += ""

$lines += "## Ports Critiques exposes"
if ($results.network_audit.exposed_ports.Count -eq 0) {
    $lines += "Aucun port critique expose sur 0.0.0.0. OK."
} else {
    foreach ($p in $results.network_audit.exposed_ports) { $lines += "- $p" }
}
$lines += ""

$lines += "## Binds 0.0.0.0 dans le code"
if ($results.network_audit.bind_global_files.Count -eq 0) {
    $lines += "Aucun bind global detecte dans le code source."
} else {
    foreach ($f in $results.network_audit.bind_global_files) {
        $lines += "- $($f.File):$($f.Line) -> ``$($f.Text)``"
    }
}
$lines += ""

$out = $lines -join "`n"
if ($OutFile) {
    $out | Out-File -Encoding utf8 $OutFile
    Write-Host "`nOK -> $OutFile" -ForegroundColor Green
} else {
    $out
}
