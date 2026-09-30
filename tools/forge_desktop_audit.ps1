# forge_desktop_audit.ps1 — audit + repair raccourcis bureau Nokido post Phase 1+23.
# Usage : powershell -ExecutionPolicy Bypass -File tools/forge_desktop_audit.ps1
#         powershell -ExecutionPolicy Bypass -File tools/forge_desktop_audit.ps1 -Fix
param([switch]$Fix = $false)

$sh = New-Object -ComObject WScript.Shell

# Tous les paths bureau possibles (Win11 + OneDrive)
$paths = @(
    [Environment]::GetFolderPath('Desktop'),
    "$env:USERPROFILE\Desktop",
    "$env:USERPROFILE\OneDrive\Desktop",
    "$env:USERPROFILE\OneDrive - Personnel\Desktop",
    "C:\Users\Public\Desktop"
) | Where-Object { Test-Path $_ -ErrorAction SilentlyContinue } | Select-Object -Unique

Write-Host "=== Paths scannes ==="
$paths | ForEach-Object { Write-Host "  $_" }
Write-Host ""

$found = @()
foreach ($p in $paths) {
    Get-ChildItem -Path $p -Filter '*.lnk' -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $lnk = $sh.CreateShortcut($_.FullName)
            $target = $lnk.TargetPath
            $args   = $lnk.Arguments
            $wd     = $lnk.WorkingDirectory
            # Filtre : nom contient nokido/lf OR target/args mentionne nssm/nokido
            if ($_.Name -match 'nokido|LaF|forge' -or
                $target -match 'nokido|nssm|miniforge|Nokido' -or
                $args   -match 'Nokido|nssm') {
                $found += [pscustomobject]@{
                    File   = $_.FullName
                    Name   = $_.Name
                    Target = $target
                    Args   = $args
                    WD     = $wd
                }
            }
        } catch {
            Write-Warning "Cannot read $($_.FullName)"
        }
    }
}

Write-Host "=== Raccourcis Nokido trouves : $($found.Count) ===`n"
$found | Format-Table File, Name, Target, Args -AutoSize -Wrap

# DIAG : patterns problematiques post-Phase 1+23
Write-Host "`n=== Patterns problematiques detectes ==="
$issues = @()
foreach ($s in $found) {
    $full = "$($s.Target) $($s.Args)"
    # Phase 1 : NokidoBrainWorkerRust = Disabled NSSM. Si raccourci fait nssm start dessus -> fail
    if ($full -match 'nssm.*\b(start|restart)\b.*NokidoBrainWorkerRust') {
        $issues += "[$($s.Name)] cible 'nssm start NokidoBrainWorkerRust' = service Disabled. Remplacer par POST /supervisor/wake/NokidoBrainWorkerRust"
    }
    # Phase 23 : services bypass via NSSM direct = redondant avec supervisor
    if ($full -match 'nssm.*\b(start|stop|restart)\b.*Nokido(MCP|Hebbian|Graph|Searxng|Homeostasis|Watchdog|Recon|TaskExecutor|MemoryConsolidator|OfflineTrainer|NightTrainer|SelfPatcher|GeminiDaemon|RSSWatcher)') {
        $issues += "[$($s.Name)] cible 'nssm ...' sur service deja gere par supervisor.toml. Migration vers POST /api/services/{start|stop|restart}/{name} hub :8766 recommandee"
    }
    # NSSM NokidoMCP direct = INTERDIT memory feedback_hub_restart_pattern
    if ($full -match 'nssm.*\brestart\b.*NokidoMCP\b') {
        $issues += "[$($s.Name)] 'nssm restart NokidoMCP' = INTERDIT (crash loop port 8766). Utiliser 'nssm restart LaForge-Master'"
    }
}
if ($issues.Count -eq 0) {
    Write-Host "  Aucun pattern problematique." -ForegroundColor Green
} else {
    $issues | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
}

if (-not $Fix) {
    Write-Host "`n>>> Mode AUDIT (read-only). Pour patcher : -Fix"
    return
}

# === MODE FIX ===
Write-Host "`n=== MODE FIX ==="
if ($found.Count -eq 0) {
    Write-Host "  Rien a patcher."
    return
}
$root = "$env:USERPROFILE\Script python IA\Nokido"
foreach ($s in $found) {
    $full = "$($s.Target) $($s.Args)"
    $new_target = $null
    $new_args   = $null
    if ($full -match 'nssm.*\bstart\b.*NokidoBrainWorkerRust') {
        $new_target = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        $new_args   = "-NoProfile -Command `"Invoke-WebRequest -Method POST -Uri http://127.0.0.1:8766/api/services/start/NokidoBrainWorkerRust -Headers @{Authorization='Bearer ' + (Get-Content '$root\LaForge.env' | Select-String '^FORGE_MCP_TOKEN' | ForEach-Object { (`$_ -split '=',2)[1].Trim() })}`""
    }
    elseif ($full -match 'nssm.*\brestart\b.*NokidoMCP\b') {
        $new_target = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
        $new_args   = "restart LaForge-Master"
    }
    if ($new_target) {
        Write-Host "PATCH $($s.Name)" -ForegroundColor Cyan
        Write-Host "  AVANT : $($s.Target) $($s.Args)"
        Write-Host "  APRES : $new_target $new_args"
        $lnk = $sh.CreateShortcut($s.File)
        $lnk.TargetPath = $new_target
        $lnk.Arguments  = $new_args
        $lnk.Save()
        Write-Host "  OK" -ForegroundColor Green
    }
}
Write-Host "`n=== Fini ==="
