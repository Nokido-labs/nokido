#Requires -Version 5.1
# Nokido - One-time : RIEN ne se lance au boot Windows.
#   - tous les services LaForge/netcfg/Cowork/Trace + superviseur Master -> Manual
#   - taches planifiees Nokido (dont WakeRespawn = relance au reveil-veille) -> Disabled
#   - VeraCrypt + LM Studio retires du demarrage (HKCU Run + startup folder)
# Reversible (Manual != supprime). Reveil a la demande : tools\wake_stack.bat

if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

$Host.UI.RawUI.WindowTitle = "Nokido - Disable autostart"
Write-Host ""
Write-Host "Nokido - RIEN au boot (services Manual + VeraCrypt/LM Studio off)" -ForegroundColor Yellow
Write-Host "Tout reste inactif au demarrage Windows. Reveil = tools\wake_stack.bat" -ForegroundColor DarkGray
Write-Host ""

# --- 1. Services Nokido / netcfg / Cowork / Trace + superviseur -> Manual (dynamique) ---
Write-Host "[1] Services -> Manual" -ForegroundColor Cyan
$svc = Get-Service | Where-Object { $_.Name -match '^Nokido|^netcfg|^LaForge|Cowork|TraceCollector' } | Sort-Object Name
foreach ($s in $svc) {
    try {
        Set-Service -Name $s.Name -StartupType Manual -ErrorAction Stop
        Write-Host ("    [OK] {0,-34} -> Manual (etat={1})" -f $s.Name, $s.Status) -ForegroundColor Green
    } catch {
        Write-Host ("    [!!] {0,-34} {1}" -f $s.Name, $_.Exception.Message) -ForegroundColor Red
    }
}
if (-not $svc) { Write-Host "    (aucun service LaForge/netcfg trouve)" -ForegroundColor DarkGray }

# --- 2. Taches planifiees Nokido -> Disabled ---
Write-Host "[2] Taches planifiees Nokido -> Disabled" -ForegroundColor Cyan
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskName -match 'Nokido|forge|WakeRespawn|pulse|sentinel' -and $_.State -ne 'Disabled' }
foreach ($t in $tasks) {
    try {
        Disable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop | Out-Null
        Write-Host ("    [OK] {0}{1}" -f $t.TaskPath, $t.TaskName) -ForegroundColor Green
    } catch {
        Write-Host ("    [!!] {0} {1}" -f $t.TaskName, $_.Exception.Message) -ForegroundColor Red
    }
}
if (-not $tasks) { Write-Host "    (aucune tache active)" -ForegroundColor DarkGray }

# --- 3. VeraCrypt + LM Studio : retirer du demarrage ---
Write-Host "[3] VeraCrypt / LM Studio autostart -> off" -ForegroundColor Cyan
# Mesure 2026-08-25 : la cle posee par LM Studio s'appelle 'electron.app.LM Studio'
# (valeur "...\LM Studio.exe --run-as-service"). Un match sur des noms EXACTS la ratait
# en silence. On enumere les valeurs presentes et on filtre par motif.
$run = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
$rx  = 'VeraCrypt|LM ?Studio|lm-studio|LMStudio'
$props = (Get-Item -Path $run -ErrorAction SilentlyContinue).Property
if ($null -eq $props) { Write-Host "    [!!] HKCU\Run illisible" -ForegroundColor Red }
foreach ($n in @($props | Where-Object { $_ -match $rx })) {
    Remove-ItemProperty -Path $run -Name $n -Force
    Write-Host "    [OK] HKCU\Run\$n retire" -ForegroundColor Green
}
$sf = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$found = Get-ChildItem $sf -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'VeraCrypt|LM ?Studio|Nokido' }
foreach ($f in $found) { Write-Host "    [i] startup-folder: $($f.Name) -> supprimer manuellement si indesirable" -ForegroundColor Yellow }
if (-not $found) { Write-Host "    (startup-folder propre)" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "RESTE a decocher DANS les apps (non scriptable) :" -ForegroundColor Yellow
Write-Host "  VeraCrypt > Settings > Preferences :" -ForegroundColor Gray
Write-Host "     - decocher 'Start VeraCrypt Background Task'" -ForegroundColor Gray
Write-Host "     - decocher 'Mount favorite volumes when logged on'  (GARDER V: comme favori)" -ForegroundColor Gray
Write-Host "  LM Studio > Settings :" -ForegroundColor Gray
Write-Host "     - desactiver 'Run on startup' / 'Start LLM server on login' / 'Minimize to tray'" -ForegroundColor Gray
Write-Host ""
Write-Host "Termine. RIEN ne demarre au boot. Reveil : tools\wake_stack.bat" -ForegroundColor Cyan
Write-Host "Appuyer sur une touche pour fermer..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
