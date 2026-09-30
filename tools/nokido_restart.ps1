# Restart ROBUSTE de la flotte web Nokido.
# stop -> attend la FERMETURE REELLE des ports -> start.
# Le nokido_stop.ps1 s'auto-eleve / detache : un Start-Sleep fixe ne suffit pas
# (le start partait avant la mort des process -> ports tenus -> remonte mal).
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Le Stop s'auto-eleve et se detache : cet appel rend la main AVANT que l'arret
# ait commence. On ne peut donc pas l'attendre — on attend son SIGNAL DE FIN.
$doneFlag = Join-Path (Split-Path -Parent $here) 'sandbox\nokido_stop.done'
if (Test-Path $doneFlag) { Remove-Item $doneFlag -Force -ErrorAction SilentlyContinue }
& (Join-Path $here 'nokido_stop.ps1') -NoWait

# Attente du SIGNAL, pas d'un port. Sonder :7400 pendant 20 s ne disait rien de
# l'arret : le Stop coupe encore Ollama, Docker et les orphelins bien apres la
# fermeture de ce port, et le Start partait au milieu du carnage. C'est la cause
# pour laquelle seul un stop-puis-start MANUEL fonctionnait (mesure 2026-08-17).
$deadline = (Get-Date).AddSeconds(240)
Write-Host "  Attente de la fin REELLE du stop (signal $doneFlag)..." -ForegroundColor DarkGray
while (-not (Test-Path $doneFlag) -and (Get-Date) -lt $deadline) {
  Start-Sleep -Milliseconds 800
}
if (Test-Path $doneFlag) {
  Write-Host "  [OK] stop termine — lancement du start." -ForegroundColor Green
} else {
  Write-Host "  [!] pas de signal apres 240s — start lance quand meme (verifier la fenetre du stop)." -ForegroundColor Yellow
}

Start-Sleep -Seconds 2
# Start lance comme process SEPARE (decouple du wrapper) = identique a un lancement
# manuel de nokido_start.ps1 (qui remonte :7400 de facon fiable). Un '&' imbrique
# herite du contexte du wrapper et cassait le spawn interactif de :7400.
Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $here 'nokido_start.ps1')
