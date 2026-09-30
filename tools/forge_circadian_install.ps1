# tools/forge_circadian_install.ps1
# Installe 6 taches planifiees Windows pour le rythme circadien Nokido.
# A lancer en Administrateur :
#   PowerShell -ExecutionPolicy Bypass -File tools\forge_circadian_install.ps1
#
# Une tache par phase, lancement quotidien a l heure physiologique :
#   LaForge-Circadian-Aurore     06:00  (cortisol/cortex prefrontal)
#   LaForge-Circadian-Jour       09:00  (estomac/cortex moteur/associatif)
#   LaForge-Circadian-Crepuscule 18:00  (pineale/rein)
#   LaForge-Circadian-NREM1      22:00  (hippocampe consolidation)
#   LaForge-Circadian-NREM3      02:00  (cortex visuel/temporal replay)
#   LaForge-Circadian-REM        04:00  (glymphatique cleanup)
#
# Chaque tache appelle forge_circadian_runner.py --fire PHASE.
# Desinstaller : schtasks /delete /tn "LaForge-Circadian-*" /f

$ErrorActionPreference = "Stop"

$python = "$env:USERPROFILE\miniforge3\python.exe"
$runner = "$env:USERPROFILE\Script python IA\Nokido\tools\forge_circadian_runner.py"

if (-not (Test-Path $python)) { throw "Python introuvable : $python" }
if (-not (Test-Path $runner)) { throw "Runner introuvable : $runner" }

$phases = @(
    @{ Name = "Aurore"     ; Time = "06:00" ; Phase = "AURORE" }
    @{ Name = "Jour"       ; Time = "09:00" ; Phase = "JOUR" }
    @{ Name = "Crepuscule" ; Time = "18:00" ; Phase = "CREPUSCULE" }
    @{ Name = "NREM1"      ; Time = "22:00" ; Phase = "NREM1" }
    @{ Name = "NREM3"      ; Time = "02:00" ; Phase = "NREM3" }
    @{ Name = "REM"        ; Time = "04:00" ; Phase = "REM" }
)

foreach ($p in $phases) {
    $taskName = "LaForge-Circadian-$($p.Name)"
    # /tr doit etre une seule string. On embed python + runner + --fire PHASE.
    $tr = "`"$python`" `"$runner`" --fire $($p.Phase)"
    Write-Host "==> $taskName  @ $($p.Time)  -> phase=$($p.Phase)"
    # Recree (idempotent). schtasks /delete affiche erreur si tache absente ;
    # 2>$null + |Out-Null n absorbent pas la sortie native PowerShell -
    # solution : capture stdout+stderr fusionnes dans variable + drop.
    $null = & schtasks /delete /tn $taskName /f 2>&1
    $createOut = & schtasks /create /tn $taskName `
        /tr $tr `
        /sc daily /st $p.Time `
        /ru "SYSTEM" `
        /rl HIGHEST `
        /f 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning ("schtasks /create echec pour {0} (exit={1}) : {2}" -f $taskName, $LASTEXITCODE, ($createOut -join ' '))
    } else {
        Write-Host "    OK"
    }
}

Write-Host "`n=== Verification ==="
# /query supporte le wildcard /tn dans certaines versions, mais retour exit=1
# si zero match. Drop l erreur, montre juste le contenu si present.
$qOut = & schtasks /query /tn "LaForge-Circadian-Aurore" /fo TABLE 2>&1
Write-Host ($qOut -join "`n")

Write-Host "`nInstalle. Pour declencher manuellement : schtasks /run /tn LaForge-Circadian-<Phase>"
Write-Host "Pour status : python tools\forge_circadian_runner.py --status"
Write-Host "Pour desinstaller : schtasks /delete /tn 'LaForge-Circadian-*' /f"
